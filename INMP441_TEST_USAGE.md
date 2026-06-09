```bash
sudo apt update
sudo apt install -y alsa-utils python3
python3 inmp441_test.py --list
python3 inmp441_test.py -D default -d 5 -o test.wav
```

If `default` does not work, try one of the devices shown by `--list`, for example:

```bash
python3 inmp441_test.py -D plughw:0,0 -d 5 -o test.wav
python3 inmp441_test.py -D plughw:1,0 -d 5 -o test.wav
```

For a live sound level meter:

```bash
python3 inmp441_test.py -D default --meter
```

Typical INMP441 wiring to Raspberry Pi 40-pin header:
#怎麼接INMP441
| INMP441 | Raspberry Pi |
| --- | --- |
| VDD | 3.3V |
| GND | GND |
| SCK/BCLK | GPIO18, pin 12 |
| WS/LRCL | GPIO19, pin 35 |
| SD/DOUT | GPIO20, pin 38 |
| L/R | GND for left channel, 3.3V for right channel |

Bookworm usually also needs an I2S microphone overlay in `/boot/firmware/config.txt`.
The exact overlay name depends on your image/kernel. Common checks:

```bash
grep -i i2s /boot/firmware/config.txt
dtoverlay -h | grep -i -E "i2s|mic|inmp|dmic"
arecord -l
```

The program prints peak and RMS levels after recording. If both are near zero,
check wiring, the ALSA device name, and whether the I2S overlay is enabled.
