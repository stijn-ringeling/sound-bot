import array
import ctypes
import os
import sys
import ctypes.util

from darkPy import helpers

log = helpers.setup_logger()
c_int_ptr = ctypes.POINTER(ctypes.c_int)
c_int16_ptr = ctypes.POINTER(ctypes.c_int16)
c_float_ptr = ctypes.POINTER(ctypes.c_float)


class EncoderStruct(ctypes.Structure):
    pass


EncoderStructPtr = ctypes.POINTER(EncoderStruct)

exported_functions = [
    ('opus_strerror', [ctypes.c_int], ctypes.c_char_p),
    ('opus_encoder_get_size', [ctypes.c_int], ctypes.c_int),
    ('opus_encoder_create', [ctypes.c_int, ctypes.c_int, ctypes.c_int, c_int_ptr], EncoderStructPtr),
    ('opus_encode', [EncoderStructPtr, c_int16_ptr, ctypes.c_int, ctypes.c_char_p, ctypes.c_int32], ctypes.c_int32),
    ('opus_encoder_ctl', None, ctypes.c_int32),
    ('opus_encoder_destroy', [EncoderStructPtr], None)
]


def libopus_loader(name):
    lib = ctypes.cdll.LoadLibrary(name)

    for item in exported_functions:
        try:
            func = getattr(lib, item[0])
        except Exception as e:
            raise e

        try:
            if item[1]:
                func.argtypes = item[1]

            func.restype = item[2]
        except KeyError:
            pass

    return lib


try:
    if sys.platform == 'win32':
        _basedir = os.path.dirname(os.path.abspath(__file__))
        _bitness = 'x64' if sys.maxsize > 2**32 else 'x86'
        _filename = os.path.join(_basedir, os.path.join('bin', 'libopus-0.{}.dll'.format(_bitness)))
        log.debug("Loaded opus from {}".format(_filename))
        _lib = libopus_loader(_filename)
    else:
        _filename = ctypes.util.find_library('opus')
        log.info("Loaded opus from {}".format(_filename))
        _lib = libopus_loader(_filename)
except Exception as e:
    _lib = None

def load_opus(name):
    global _lib
    _lib = libopus_loader(name)

def is_loaded():
    global  _lib
    return _lib is not None

class OpusError(Exception):

    def __init__(self, code):
        self.code = code
        msg = _lib.opus_strerror(self.code).decode('utf-8')
        log.info('"{} has happened'.format(msg))
        super().__init__(msg)

class OpusNotLoaded(Exception):
    """
    An exception that is thrown for when libopus is not loaded.
    """
OK = 0
APPLICATION_AUDIO    = 2049
APPLICATION_VOIP     = 2048
APPLICATION_LOWDELAY = 2051
CTL_SET_BITRATE      = 4002
CTL_SET_BANDWIDTH    = 4008
CTL_SET_FEC          = 4012
CTL_SET_PLP          = 4014
CTL_SET_SIGNAL       = 4024

band_ctl = {
    'narrow': 1101,
    'medium': 1102,
    'wide': 1103,
    'superwide': 1104,
    'full': 1105,
}

signal_ctl = {
    'auto': -1000,
    'voice': 3001,
    'music': 3002,
}

class Encoder:
    def __init__(self, sampling, channels, application=APPLICATION_AUDIO):
        self.sampling_rate = sampling
        self.channels = channels
        self.application = application

        self.frame_length = 20
        self.sample_size = 2 * self.channels # (bit_rate / 8) but bit_rate == 16
        self.samples_per_frame = int(self.sampling_rate / 1000 * self.frame_length)
        self.frame_size = self.samples_per_frame * self.sample_size

        if not is_loaded():
            raise OpusNotLoaded()

        self._state = self._create_state()
        self.set_bitrate(128)
        self.set_fec(True)
        self.set_expected_packet_loss_percent(0.15)
        self.set_bandwidth('full')
        self.set_signal_type('auto')

    def __del__(self):
        if hasattr(self, '_state'):
            _lib.opus_encoder_destroy(self._state)
            self._state = None

    def _create_state(self):
        ret = ctypes.c_int()
        result = _lib.opus_encoder_create(self.sampling_rate, self.channels, self.application, ctypes.byref(ret))

        if ret.value != 0:
            log.info('error has happened in state creation')
            raise OpusError(ret.value)

        return result

    def set_bitrate(self, kbps):
        kbps = min(128, max(16, int(kbps)))

        ret = _lib.opus_encoder_ctl(self._state, CTL_SET_BITRATE, kbps * 1024)
        if ret < 0:
            log.info('error has happened in set_bitrate')
            raise OpusError(ret)

        return kbps

    def set_bandwidth(self, req):
        if req not in band_ctl:
            raise KeyError('%r is not a valid bandwith setting. Try one of: %s' % (req, ','.join(band_ctl)))

        k = band_ctl[req]
        ret = _lib.opus_encoder_ctl(self._state, CTL_SET_BANDWIDTH, k)

        if ret < 0:
            log.info('error has happened in set_bandwith', k)
            raise OpusError(ret)

    def set_fec(self, enabled=True):
        ret = _lib.opus_encoder_ctl(self._state, CTL_SET_FEC, 1 if enabled else 0)

        if ret < 0:
            log.info('error has happened in set_fec')
            raise OpusError(ret)

    def set_expected_packet_loss_percent(self, percentage):
        ret = _lib.opus_encoder_ctl(self._state, CTL_SET_PLP, min(100, max(0, int(percentage * 100))))

        if ret < 0:
            log.info('error has happened in set_expected_packet_loss_percent')
            raise OpusError(ret)

    def encode(self, pcm, frame_size):
        max_data_bytes = len(pcm)
        pcm = ctypes.cast(pcm, c_int16_ptr)
        data = (ctypes.c_char * max_data_bytes)()

        ret = _lib.opus_encode(self._state, pcm, frame_size, data, max_data_bytes)
        if ret < 0:
            log.info('error has happened in encode')
            raise OpusError(ret)

        return array.array('b', data[:ret]).tobytes()

    def set_signal_type(self, req):
        if req not in signal_ctl:
            raise ValueError("%r is not a valid signal type setting. Try one of: %s" % (req, ','.join(signal_ctl)))

        k = signal_ctl[req]
        ret = _lib.opus_encoder_ctl(self._state, CTL_SET_SIGNAL, k)

        if ret < 0:
            log.info('Error occured in set_signal_type')
            raise OpusError(ret)
