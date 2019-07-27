
from . import constants
from .constants import Pins, Commands, Registers, DisplayModes
from .spi import SPI

from time import sleep

from PIL import Image
import RPi.GPIO as GPIO
import numpy as np

# TODO: the high-level functions should probably be in their own class

class EPD:
    '''
    An interface to the electronic paper display (EPD).

    Parameters
    ----------

    vcom : float
         The VCOM voltage that produces optimal contrast. Varies from
         device to device.
    '''

    def __init__(self, vcom=-1.5):

        # bus 0, device 0
        self.spi = SPI()

        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        # GPIO.setup(Pins.CS, GPIO.OUT, initial=GPIO.HIGH)
        GPIO.setup(Pins.HRDY, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
        GPIO.setup(Pins.RESET, GPIO.OUT, initial=GPIO.HIGH)

        # reset
        GPIO.output(Pins.RESET, GPIO.LOW)
        sleep(0.1)
        GPIO.output(Pins.RESET, GPIO.HIGH)

        self.width  = None
        self.height = None
        self.img_buf_address  = None
        self.firmware_version = None
        self.lut_version      = None
        self.update_system_info()

        self.frame_buf = Image.new('L', (self.width, self.height), 0xFF)
        self.prev_frame = None  # for automatic partial update

        # TODO: should send INIT command probably

        # enable I80 packed mode
        self.write_register(Registers.I80CPCR, 0x1)

        self.set_vcom(vcom)

    def __del__(self):
        GPIO.cleanup()

    def write_cmd(self, cmd, *args):
        '''
        Send the device a command code

        Parameters
        ----------

        cmd : int (from constants.Commands)
            The command to send

        args : list(int), optional
            Arguments for the command
        '''
        # print('sending command {:x} with data {}'.format(cmd, str(args)))
        #GPIO.output(Pins.CS, GPIO.LOW)
        self.spi.write(0x6000, [cmd])  # 0x6000 is preamble
        #GPIO.output(Pins.CS, GPIO.HIGH)

        for arg in args:
            # print('arg:', arg)
            self.write_data(arg)

    def write_data(self, ary):
        '''
        Send the device an array of data

        Parameters
        ----------

        ary : array-like
            The data
        '''
        # GPIO.output(Pins.CS, GPIO.LOW)
        self.spi.write(0x0000, ary)
        # GPIO.output(Pins.CS, GPIO.HIGH)

    def read_data(self, n):
        '''
        Read n 16-bit words of data from the device

        Parameters
        ----------

        n : int
            The number of 2-byte words to read
        '''
        # TODO: add buf as argument?
        # GPIO.output(Pins.CS, GPIO.LOW)
        rtn = self.spi.read(0x1000, n)
        # GPIO.output(Pins.CS, GPIO.HIGH)
        return rtn

    def read_int(self):
        '''
        Read a single 16 bit int from the device
        '''
        recv = self.read_data(1)[0]
        return recv

    def run(self):
        self.write_cmd(Commands.SYS_RUN)

    def standby(self):
        self.write_cmd(Commands.STANDBY)

    def sleep(self):
        self.write_cmd(Commands.SLEEP)

    def read_register(self, address):
        self.write_cmd(Commands.REG_RD, address)
        return self.read_int()

    def write_register(self, address, val):
        self.write_cmd(Commands.REG_WR, address)
        self.write_data((val,))

    def mem_burst_read_trigger(self, address, count):
        # these are both 32 bits, so we need to split them
        # up into two 16 bit values

        addr0 = address & 0xFFFF
        addr1 = address >> 16

        len0 = count & 0xFFFF
        len1 = count >> 16

        self.write_cmd(Commands.MEM_BST_RD_T,
                       addr0, addr1, len0, len1)

    def mem_burst_read_start(self):
        self.write_cmd(Commands.MEM_BST_RD_S)

    def mem_burst_write(self, address, count):
        addr0 = address & 0xFFFF
        addr1 = address >> 16

        len0 = count & 0xFFFF
        len1 = count >> 16

        self.write_cmd(Commands.MEM_BST_WR,
                       addr0, addr1, len0, len1)

    def mem_burst_end(self):
        self.write_cmd(Commands.MEM_BST_END)

    def get_vcom(self):
        self.write_cmd(Commands.VCOM, 0)
        vcom_int = self.read_int()
        return -vcom_int/1000

    def set_vcom(self, vcom):
        self._validate_vcom(vcom)
        vcom_int = int(-1000*vcom)
        self.write_cmd(Commands.VCOM, 1, vcom_int)

    def _validate_vcom(self, vcom):
        # TODO: figure out the actual limits for vcom
        if not -5 < vcom < 0:
            raise ValueError("vcom must be between -5 and 0")

    def update_system_info(self):
        self.write_cmd(Commands.GET_DEV_INFO)
        data = self.read_data(20)
        self.width  = data[0]
        self.height = data[1]
        self.img_buf_address = data[3] << 16 | data[2]
        self.firmware_version = ''.join([chr(x>>8)+chr(x&0xFF) for x in data[4:12]])
        self.lut_version      = ''.join([chr(x>>8)+chr(x&0xFF) for x in data[12:20]])

    def set_img_buf_base_addr(self, address):
        word0 = address >> 16
        word1 = address & 0xFFFF
        self.write_register(Registers.LISAR+2, word0)
        self.write_register(Registers.LISAR, word1)

    def wait_display_ready(self):
        while(self.read_register(Registers.LUTAFSR)):
            sleep(0.01)

    def load_img_start(self, endian_type, pixel_format, rotate_mode):
        arg = (endian_type << 8) | (pixel_format << 4) | rotate_mode
        self.write_cmd(Commands.LD_IMG, arg)

    def load_img_area_start(self, endian_type, pixel_format, rotate_mode, xy, dims):
        arg0 = (endian_type << 8) | (pixel_format << 4) | rotate_mode
        self.write_cmd(Commands.LD_IMG_AREA, arg0, xy[0], xy[1], dims[0], dims[1])

    def load_img_end(self):
        self.write_cmd(Commands.LD_IMG_END)

    def packed_pixel_write(self, endian_type, pixel_format, rotate_mode, xy=None, dims=None):
        self.set_img_buf_base_addr(self.img_buf_address)
        if xy is None:
            self.load_img_start(endian_type, pixel_format, rotate_mode)
        else:
            self.load_img_area_start(endian_type, pixel_format, rotate_mode, xy, dims)

        if xy is None:
            self.spi.write_pixels(self.frame_buf.getdata())
        else:
            buf = np.array(self.frame_buf.getdata(), dtype=np.uint8).reshape(self.height, self.width)

            xmin = xy[0]
            xmax = xy[0] + dims[0]
            ymin = xy[1]
            ymax = xy[1] + dims[1]

            partial_buf = buf[ymin:ymax, xmin:xmax].flatten() # extract relevant portion

            self.spi.write_pixels(partial_buf)

        self.load_img_end()

    def display_area(self, xy, dims, display_mode):
        self.write_cmd(Commands.DPY_AREA, xy[0], xy[1], dims[0], dims[1], display_mode)

    def display_area_1bpp(self, xy, dims, display_mode, background_gray, foreground_gray):

        # set display to 1bpp mode
        old_value = self.read_register(Registers.UP1SR+2)
        self.write_register(Registers.UP1SR+2, old_val | (1<<2))

        # set color table
        self.write_register(Registers.BGVR, (background_gray << 8) | foreground_gray)

        # display image
        self.display_area(xy, dims, display_mode)
        self.wait_display_ready()

        # back to normal mode
        old_value = self.read_register(Registers.UP1SR+2)
        self.write_register(Registers.UP1SR+2, old_value & ~(1<<2))

    def display_area_buf(self, xy, dims, display_mode, display_buf_address):
        self.write_cmd(Commands.DPY_BUF_AREA, xy[0], xy[1], dims[0], dims[1], display_mode,
                       display_buf_address & 0xFFFF, display_buf_address >> 16)

    def write_full(self, mode):
        '''
        Write the full image to the device, and display it using mode
        '''

        # send image to controller
        self.wait_display_ready()
        self.packed_pixel_write(
            constants.EndianTypes.BIG,
            constants.PixelModes.M_8BPP,
            constants.Rotate.NONE,
        )

        # display sent image
        # TODO: should not have area here?
        self.display_area(
            (0, 0),
            (self.width, self.height),
            mode
        )

        self.prev_frame = np.array(self.frame_buf).reshape(self.height, self.width)

    # TODO: write unit test for this function
    @classmethod
    def _compute_diff_box(cls, a, b):
        '''
        Find the four coordinates giving the bounding box of differences between 2D
        arrays a and b.
        '''
        y_idxs, x_idxs = np.nonzero(a != b)

        # this one is not sorted
        minx = np.amin(x_idxs)
        maxx = np.amax(x_idxs)+1

        # this one is sorted
        miny = y_idxs[0]
        maxy = y_idxs[-1]+1

        return (minx, miny, maxx, maxy)

    def write_partial(self, mode):
        '''
        Write only the rectangle bounding the pixels of the image that have changed
        since the last call to write_full or write_partial
        '''

        if self.prev_frame is None:  # first call since initialization
            self.write_full(self, mode)

        # compute diff
        frame_buf_np = np.array(self.frame_buf).reshape(self.height, self.width)
        diff_box = self._compute_diff_box(frame_buf_np, self.prev_frame)
        self.prev_frame = frame_buf_np

        # x dimension of dims must be divisible by 2
        xdim = diff_box[2]-diff_box[0]
        xdim += xdim%2

        xy = (diff_box[0], diff_box[1])
        dims = (xdim, diff_box[3]-diff_box[1])

        # send image to controller
        self.wait_display_ready()
        self.packed_pixel_write(
            constants.EndianTypes.BIG,
            constants.PixelModes.M_8BPP,
            constants.Rotate.NONE,
            xy,
            dims
        )

        # display sent image
        self.display_area(
            xy,
            dims,
            mode
        )


    def clear(self):
        '''
        Clear display, device image buffer, and frame buffer (e.g. at startup)
        '''
        # set frame buffer to all white
        self.frame_buf.paste(0xFF, box=(0, 0, self.width, self.height))
        self.write_full(DisplayModes.INIT)
