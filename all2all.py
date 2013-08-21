"""
Created on Mar 20, 2013

All2All units.

@author: Kazantsev Alexey <a.kazantsev@samsung.com>
"""
import units
import formats
import numpy
import pyopencl
import time
import rnd
import config
import logging


class All2All(units.Forward):
    """All2All with linear activation f(x) = x.

    Should be assigned before initialize():
        input

    Updates after run():
        output

    Creates within initialize():
        weights
        bias

    Attributes:
        input: input as Batch.
        output: output as Batch.
        weights: weights as Vector.
        bias: bias as Vector.
        output_shape: shape of the output layer.
        weights_amplitude: amplitude of the random distribution of weights.
        rand: rnd.Rand() object for initial weights generation.
        input_maxvle: supposed maximum value of the input value
            (used for weights generation when weights_amplitude is None).
            For better performance should be 1.0 for an input layer
            and 1.7159 for other layers if scaled tanh activation is used,
            while values of an input should be normalized to -1, 1.
        krn_: OpenCL kernel.
        s_activation: activation define for OpenCL source.
        weights_transposed: assume weights matrix as a transposed one.
    """
    def __init__(self, output_shape=None, device=None, weights_amplitude=None,
                 input_maxvle=1.7159, rand=rnd.default,
                 weights_transposed=False):
        super(All2All, self).__init__(device=device)
        self.input = None  # formats.Vector(device)
        self.output = formats.Vector(device)
        self.weights = formats.Vector(device)
        self.bias = formats.Vector(device)
        self.output_shape = output_shape
        self.weights_amplitude = weights_amplitude
        self.input_maxvle = input_maxvle
        self.rand = rand
        self.s_activation = "ACTIVATION_LINEAR"
        self.weights_transposed = weights_transposed

    def init_unpickled(self):
        super(All2All, self).init_unpickled()
        self.krn_ = None
        self.cl_sources_["%s/forward.cl" % (config.cl_dir)] = ""

    def get_weights_amplitude(self):
        """
        Returns: weights amplitude for initial random distribution,
                 such that activation function will be near maximum
                 if all input values are at their supposed max value.
        """
        return (9.0 / self.input_maxvle /
                (self.input.v.size // self.input.v.shape[0]))

    def initialize(self):
        if self.weights_amplitude == None:
            # Get weights amplitude and cap it to 0.05
            self.weights_amplitude = min(self.get_weights_amplitude(), 0.05)
        n_weights = self.input.v.size // self.input.v.shape[0] * \
                    numpy.prod(self.output_shape)
        if self.weights.v == None or self.weights.v.size != n_weights:
            self.weights.v = numpy.zeros([n_weights],
                                         dtype=config.dtypes[config.dtype])
            self.rand.fill(self.weights.v, -self.weights_amplitude,
                           self.weights_amplitude)
            self.weights.v = self.weights.v.\
                    reshape([numpy.prod(self.output_shape),
                        self.input.v.size // self.input.v.shape[0]])
            # Reshape weights as a matrix:
            if self.weights_transposed:
                a = self.weights.v.transpose().copy()
                a = a.reshape(a.size)
                self.weights.v = self.weights.v.reshape(self.weights.v.size)
                self.weights.v[:] = a[:]
                self.weights.v = self.weights.v.\
                    reshape([self.input.v.size //
                             self.input.v.shape[0],
                             numpy.prod(self.output_shape)])
            self.weights.v_ = None
        if self.bias.v == None or \
           self.bias.v.size != numpy.prod(self.output_shape):
            self.bias.v = numpy.zeros([numpy.prod(self.output_shape)],
                                      dtype=config.dtypes[config.dtype])
            self.rand.fill(self.bias.v, -self.weights_amplitude,
                           self.weights_amplitude)
            self.bias.v_ = None

        output_size = self.input.v.shape[0] * numpy.prod(self.output_shape)
        if self.output.v == None or self.output.v.size != output_size:
            self.output.v = numpy.zeros([self.input.v.shape[0],
                                             numpy.prod(self.output_shape)],
                                            dtype=config.dtypes[config.dtype])
            self.output.v_ = None

        self.input.initialize(self.device)
        self.output.initialize(self.device)
        self.weights.initialize(self.device)
        self.bias.initialize(self.device)

        if not self.device:
            return

        if self.krn_ == None:
            output_size = self.output.aligned_.size // \
                          self.output.aligned_.shape[0]
            defines = ("%s\n"
                       "%s\n"
                       "#define %s\n"
                       "#define BLOCK_SIZE %d\n"
                       "#define H %d\n"
                       "#define Y %d\n"
                       "#define Y_REAL %d\n"
                       "#define BATCH %d\n\n" %
                       ("#define WEIGHTS_TRANSPOSED"
                        if self.weights_transposed else "",
                        config.cl_defines[config.dtype], self.s_activation,
                        self.device.info.BLOCK_SIZE[config.dtype],
                        self.weights.aligned_.size // output_size, output_size,
                        self.output.v.size // self.output.v.shape[0],
                        self.output.aligned_.shape[0]))
            s = defines
            for src, define in self.cl_sources_.items():
                s += "\n" + define + "\n"
                fin = open(src, "r")
                s += fin.read()
                fin.close()
            global this_dir
            fin = open("%s/matrix_multiplication.cl" % (config.cl_dir), "r")
            s_mx_mul = fin.read()
            fin.close()
            s = s.replace("MX_MUL", s_mx_mul)
            fout = open("%s/feed_%d_%d.cl" % (config.cache_dir,
                self.input.v.size // self.input.v.shape[0],
                self.output.v.size // self.output.v.shape[0]), "w")
            fout.write(s)
            fout.close()

            self.prg_ = pyopencl.Program(self.device.context_, s).build()

            self.krn_ = pyopencl.Kernel(self.prg_, "FEED_LAYER")
            self.krn_.set_arg(0, self.input.v_)
            self.krn_.set_arg(1, self.weights.v_)
            self.krn_.set_arg(2, self.output.v_)
            self.krn_.set_arg(3, self.bias.v_)

    def print_times(self, t_start):
        """Show some statistics.
        """
        log = self.log()
        if not log.isEnabledFor(logging.DEBUG):
            return
        y = self.output.v
        self.output.sync()
        self.weights.sync()
        self.log().info("%s: %d samples with %d weights in %.2f sec "
            "(min,avg,max,sum):\ty=%.6f,%.4f,%.2f,%.2f" %
            (self.__class__.__name__, y.shape[0],
             self.weights.v.size, time.time() - t_start,
             numpy.fabs(y).min(), numpy.average(numpy.fabs(y)),
             numpy.fabs(y).max(), y.sum()))

    def gpu_run(self):
        """Forward propagation from batch on GPU.
        """
        self.input.sync(formats.GPU)
        self.weights.sync(formats.GPU)
        self.bias.sync(formats.GPU)
        output_size = int(self.output.aligned_.size //
                          self.output.aligned_.shape[0])
        global_size = [output_size, self.output.aligned_.shape[0]]
        local_size = [self.device.info.BLOCK_SIZE[config.dtype],
                      self.device.info.BLOCK_SIZE[config.dtype]]
        event = pyopencl.enqueue_nd_range_kernel(self.device.queue_, self.krn_,
                                                 global_size, local_size)
        event.wait()
        self.output.update(formats.GPU)

    def cpu_run(self):
        """Forward propagation from batch on CPU only.
        """
        self.input.sync()
        self.weights.sync()
        self.bias.sync()
        a = self.input.v.reshape([self.input.v.shape[0],
            self.input.v.size // self.input.v.shape[0]])
        b = self.weights.v
        if not self.weights_transposed:
            b = b.transpose()
        numpy.dot(a, b, self.output.v)
        self.output.v[:] += self.bias.v
        self.output.update()

    def run(self):
        t1 = time.time()
        retval = super(All2All, self).run()
        if retval:
            return retval
        self.print_times(t1)


class All2AllTanh(All2All):
    """All2All with scaled tanh() activation f(x) = 1.7159 * tanh(0.6666 * x).
    """
    def initialize(self):
        self.s_activation = "ACTIVATION_TANH"
        return super(All2AllTanh, self).initialize()

    def get_weights_amplitude(self):
        return (9.0 / (self.input_maxvle * 0.6666) /
                (self.input.v.size // self.input.v.shape[0]))

    def cpu_run(self):
        """Forward propagation from batch on CPU only.
        """
        retval = super(All2AllTanh, self).cpu_run()
        if retval:
            return retval
        self.output.sync()
        self.output.v *= 0.6666
        numpy.tanh(self.output.v, self.output.v)
        self.output.v *= 1.7159
        self.output.update()


class All2AllSoftmax(All2All):
    """All2All with linear activation and softmax normalization.

    Should be assigned before initialize():

    Updates after run():
        max_idx

    Creates within initialize():
        max_idx

    Attributes:
        krn_sm_: kernel for softmax activation calculation.
        max_idx: indexes of element with maximum value for each sample.
    """
    def __init__(self, output_shape=None, device=None, weights_amplitude=None,
                 input_maxvle=1.7159, rand=rnd.default,
                 weights_transposed=False):
        super(All2AllSoftmax, self).__init__(
            output_shape=output_shape, device=device,
            weights_amplitude=weights_amplitude, input_maxvle=input_maxvle,
            rand=rand, weights_transposed=weights_transposed)
        self.max_idx = formats.Vector()

    def init_unpickled(self):
        super(All2AllSoftmax, self).init_unpickled()
        self.krn_sm_ = None

    def get_weights_amplitude(self):
        return (9.0 / self.input_maxvle /
                (self.input.v.size // self.input.v.shape[0]))

    def initialize(self):
        itype = config.get_itype_from_size(numpy.prod(self.output_shape))
        global this_dir
        self.cl_sources_["%s/softmax.cl" % (config.cl_dir)] = (
            "#define itype %s" % (itype))
        retval = super(All2AllSoftmax, self).initialize()
        if retval:
            return retval

        if self.max_idx.v == None or \
           self.max_idx.v.size != self.output.v.shape[0]:
            self.max_idx.v = numpy.zeros(self.output.v.shape[0],
                dtype=config.itypes[itype])
            self.max_idx.v_ = None

        self.max_idx.initialize(self.device)

        if not self.device:
            return

        self.krn_sm_ = pyopencl.Kernel(self.prg_, "apply_exp")
        self.krn_sm_.set_arg(0, self.output.v_)
        self.krn_sm_.set_arg(1, self.max_idx.v_)

    def cpu_apply_exp(self):
        self.output.sync()
        log = self.log()
        if log.isEnabledFor(logging.DEBUG):
            s = []
            a = numpy.sort(self.output.v.reshape(self.output.v.size))
            for i in range(a.size - 1, a.size - 11, -1):
                s.append("%.2f" % (a[i]))
            self.log().debug("Softmax Wx+b: ", ", ".join(s),
                             ", %.2f" % (a[0]))
        for i in range(0, self.output.v.shape[0]):
            sample = self.output.v[i]
            im = sample.argmax()
            self.max_idx[i] = im
            m = sample[im]
            sample -= m
            numpy.exp(sample, sample)
            smm = sample.sum()
            sample /= smm
        self.output.update()
        self.max_idx.update()

    def gpu_apply_exp(self):
        self.output.sync(formats.GPU)
        global_size = [self.device.info.BLOCK_SIZE[config.dtype],
                       self.output.aligned_.shape[0]]
        local_size = [self.device.info.BLOCK_SIZE[config.dtype],
                      self.device.info.BLOCK_SIZE[config.dtype]]
        event = pyopencl.enqueue_nd_range_kernel(self.device.queue_,
                                                 self.krn_sm_,
                                                 global_size, local_size)
        event.wait()
        self.output.update(formats.GPU)
        self.max_idx.update(formats.GPU)

    def cpu_run(self):
        """Forward propagation from batch on CPU only.
        """
        retval = super(All2AllSoftmax, self).cpu_run()
        if retval:
            return retval
        self.cpu_apply_exp()

    def gpu_run(self):
        """Forward propagation from batch on GPU.
        """
        retval = super(All2AllSoftmax, self).gpu_run()
        if retval:
            return retval
        self.gpu_apply_exp()
