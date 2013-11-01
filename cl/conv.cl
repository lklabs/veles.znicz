/*
 * Kernels for convolutional network.
 * FIXME(a.kazantsev): due to the unified cache on GeForce Titan and higher
 *                     we can safely implement convolutional network via matrix multiplications.
 * @author: Kazantsev Alexey <a.kazantsev@samsung.com>
 */


/// @brief Feeds 2D multichannel convolutional layer with activation function:
///        linear activation: x;
///        scaled tanh activation: 1.7159 * tanh(0.6666 * x),
///        because: f(1) = 1, f(-1) = -1 and f"(x) maximum at x = 1.
/// @param h input as 2D image with interleaved channels.
/// @param weights weights.
/// @param y output.
/// @param bias bias.
/// @details y = f(h * weights + bias)
///          Should be defined externally:
///          FIXME(a.kazantsev): for performance reasons defines are better than parameters.
///          BLOCK_SIZE - optimal block size for matrix multiplication,
///          BATCH - minibatch size,
///          WIDTH - input width,
///          HEIGHT - input height,
///          N_CHANNELS - number of input channels,
///          KERNEL_WIDTH - width of the sliding window,
///          KERNEL_HEIGHT - height of the sliding window,
///          N_KERNELS - number of convolutional kernels which is the same as number of neurons.
__kernel __attribute__((reqd_work_group_size(BLOCK_SIZE, BLOCK_SIZE, 1)))
void FEED_LAYER(__global c_dtype /*IN*/ *h, __global c_dtype /*IN*/ *weights,
                __global c_dtype /*OUT*/ *y, __global c_dtype /*IN*/ *bias) {
  #define A_WIDTH (BATCH * (WIDTH - KERNEL_WIDTH + 1) * (HEIGHT - KERNEL_HEIGHT + 1))
  #define B_WIDTH N_KERNELS
  #define AB_COMMON (KERNEL_WIDTH * KERNEL_HEIGHT * N_CHANNELS)

  #define A h
  #define B weights
  #define C y

  #ifdef WEIGHTS_TRANSPOSED
  #define B_COL
  #endif

  // Matrix multiplication begins here
#ifndef N_SUM
#define BLOCKS (AB_COMMON / BLOCK_SIZE)
#if BLOCKS <= 4
#define N_SUM 2
#endif
#if (BLOCKS > 4) && (BLOCKS <= 8)
#define N_SUM 4
#endif
#if (BLOCKS > 8) && (BLOCKS <= 16)
#define N_SUM 8
#endif
#if (BLOCKS > 16) && (BLOCKS <= 32)
#define N_SUM 16
#endif
#if (BLOCKS > 32) && ((BLOCKS <= 64) || (sizeof_c_dtype > 8))
#define N_SUM 32
#endif
#if (sizeof_c_dtype <= 8) && (BLOCKS > 64) && ((BLOCKS <= 128) || (sizeof_c_dtype > 4))
#define N_SUM 64
#endif
#if (sizeof_c_dtype <= 4) && (BLOCKS > 128)
#define N_SUM 128
#endif
#endif

  // The source for matrix multiplication comes here:
  __local c_dtype AS[BLOCK_SIZE][BLOCK_SIZE]; // shared submatrix of A
  __local c_dtype BS[BLOCK_SIZE][BLOCK_SIZE]; // shared submatrix of B

  // Block index in matrix C, where the values will be put
  int bx = get_group_id(0); // from 0 to B_WIDTH / BLOCK_SIZE - 1
  int by = get_group_id(1); // from 0 to A_WIDTH / BLOCK_SIZE - 1

  // Thread index, each thread calculates one element of the resulted submatrix
  int tx = get_local_id(0); // from 0 to BLOCK_SIZE - 1
  int ty = get_local_id(1); // from 0 to BLOCK_SIZE - 1

#ifdef A_COL
  int a_offs = ty * A_WIDTH + by * BLOCK_SIZE + tx;
  #define A_OFFS A_WIDTH * BLOCK_SIZE
#else
  int a_offs = by * AB_COMMON * BLOCK_SIZE + ty * AB_COMMON + tx;
  #define A_OFFS BLOCK_SIZE
#endif

#ifdef B_COL
  #define B_OFFS B_WIDTH * BLOCK_SIZE
  int b_offs = ty * B_WIDTH + bx * BLOCK_SIZE + tx;
#else
  #define B_OFFS BLOCK_SIZE
  int b_offs = bx * AB_COMMON * BLOCK_SIZE + ty * AB_COMMON + tx;
#endif

  c_dtype sum[N_SUM];
  for (int i_sum = 0; i_sum < N_SUM; i_sum++) {
    sum[i_sum] = c_from_re(0);
    for (int i = AB_COMMON / BLOCK_SIZE * i_sum / N_SUM; i < AB_COMMON / BLOCK_SIZE * (i_sum + 1) / N_SUM; i++,
         a_offs += A_OFFS, b_offs += B_OFFS) {

      int ao = a_offs,
          bo = b_offs; // TODO(a.kazantsev): continue here.

      AS[ty][tx] = A[ao];
      BS[ty][tx] = B[bo];

      // ensure all shared loaded
      barrier(CLK_LOCAL_MEM_FENCE);

      #pragma unroll
      for(int k = 0; k < BLOCK_SIZE; k++)
      #ifdef B_COL
      #ifdef A_COL
        sum[i_sum] += c_mul(AS[k][ty], BS[k][tx]);
      #else
        sum[i_sum] += c_mul(AS[ty][k], BS[k][tx]);
      #endif
      #else
      #ifdef A_COL
        sum[i_sum] += c_mul(AS[k][ty], BS[tx][k]);
      #else
        sum[i_sum] += c_mul(AS[ty][k], BS[tx][k]);
      #endif
      #endif

      // ensure we can reload shared with new values
      barrier(CLK_LOCAL_MEM_FENCE);
    }
  }
  for (int n_sum = N_SUM; n_sum > 2; n_sum >>= 1) {
    for (int i_sum = 0; i_sum < (n_sum >> 1); i_sum++)
      sum[i_sum] = sum[i_sum << 1] + sum[(i_sum << 1) + 1];
  }
  sum[0] += sum[1];

  int idx = get_global_id(1) * B_WIDTH + get_global_id(0);
    // same as: by * B_HEIGHT * BLOCK_SIZE + bx * BLOCK_SIZE + ty * B_HEIGHT + tx

  #undef A_OFFS
  #undef B_OFFS
// The source for matrix multiplication ends here (the result will be in sum[0]).

#undef A_WIDTH
#undef B_WIDTH
#undef AB_COMMON

#undef A
#undef B
#undef C

if(!ty) // read from memory only for the first row
  AS[0][tx] = bias[bx * BLOCK_SIZE + tx];

barrier(CLK_LOCAL_MEM_FENCE);

c_dtype s = sum[0] + AS[0][tx];
#ifdef ACTIVATION_LINEAR
y[idx] = s;
#endif
#ifdef ACTIVATION_TANH
y[idx] = c_tanh(s * (dtype)0.6666) * (dtype)1.7159;
#endif
}