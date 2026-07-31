import logging
import serial
import threading
import time
from datetime import datetime

_LOGGER = logging.getLogger(__name__)


class GL865TModem:
    """AT Command Driver for Telit GL865 GSM Module."""

    def __init__(self, port: str, baudrate: int) -> None:
        self.port = port
        self.baudrate = baudrate
        self.lock = threading.Lock()

    def send_sms(self, targets: list[str], message: str) -> bool:
        """Send SMS messages to multiple recipients waiting for network confirmation."""
        with self.lock:
            ser = None
            try:
                ser = serial.Serial(self.port, self.baudrate, timeout=3)
                time.sleep(0.2)

                ser.write(b'AT+CMGF=1\r')
                time.sleep(0.3)
                ser.write(b'AT+CSCS="GSM"\r')
                time.sleep(0.3)
                ser.reset_input_buffer()

                for number in targets:
                    try:
                        ser.write(f'AT+CMGS="{number}"\r'.encode())

                        prompt_ok = False
                        start_time = time.time()
                        while time.time() - start_time < 4:
                            if ser.in_waiting:
                                chunk = ser.read(ser.in_waiting).decode("latin1", errors="ignore")
                                if ">" in chunk:
                                    prompt_ok = True
                                    break
                            time.sleep(0.1)

                        if not prompt_ok:
                            _LOGGER.error("GL865T: Modem prompt '>' not received (%s). Aborting.", number)
                            ser.write(b'\x1b')
                            time.sleep(1)
                            continue

                        ser.write(f'{message}\x1a'.encode())

                        ack_ok = False
                        ack_start = time.time()
                        response_buf = ""

                        while time.time() - ack_start < 10:
                            if ser.in_waiting:
                                chunk = ser.read(ser.in_waiting).decode("latin1", errors="ignore")
                                response_buf += chunk
                                if "OK" in response_buf or "+CMGS:" in response_buf:
                                    ack_ok = True
                                    break
                                elif "ERROR" in response_buf:
                                    _LOGGER.error("GL865T: Modem error response (%s): %s", number, response_buf.strip())
                                    break
                            time.sleep(0.3)

                        if not ack_ok:
                            _LOGGER.warning("GL865T: Network acknowledge timeout (%s).", number)

                    except Exception as num_err:
                        _LOGGER.error("GL865T: Error processing recipient (%s): %s", number, num_err)

                    time.sleep(2)

                return True
            except Exception as e:
                _LOGGER.error("GL865T: Serial port error: %s", e)
                return False
            finally:
                if ser and ser.is_open:
                    ser.close()

    def read_unread_sms(self) -> list[dict]:
        """Read SMS messages in PDU mode (UCS2 & GSM-7) and parse UDH headers."""
        with self.lock:
            ser = None
            messages = []
            try:
                ser = serial.Serial(self.port, self.baudrate, timeout=5)
                time.sleep(0.3)
                ser.reset_input_buffer()

                ser.write(b'AT+CMGF=0\r')
                time.sleep(0.3)
                ser.reset_input_buffer()

                ser.write(b'AT+CMGL=4\r')

                raw_bytes = b""
                while True:
                    chunk = ser.read(ser.in_waiting or 1)
                    if not chunk:
                        break
                    raw_bytes += chunk
                    if b"\r\nOK\r\n" in raw_bytes or b"ERROR" in raw_bytes:
                        break

                raw_data = raw_bytes.decode("latin1", errors="ignore").strip()

                if "+CMGL:" in raw_data:
                    lines = [l.strip() for l in raw_data.split('\n') if l.strip()]

                    for i in range(len(lines)):
                        if lines[i].startswith("+CMGL:"):
                            if i + 1 < len(lines) and not lines[i+1].startswith("+CMGL:") and lines[i+1] != "OK":
                                pdu = lines[i+1]
                                try:
                                    parsed = self._decode_pdu(pdu)
                                    if parsed:
                                        messages.append(parsed)
                                except Exception as err:
                                    _LOGGER.error("GL865T: PDU parsing error (%s): %s", pdu, err)

            except Exception as e:
                _LOGGER.warning("GL865T: SMS read error: %s", e)
            finally:
                if ser and ser.is_open:
                    ser.close()
            return messages

    def _decode_pdu(self, pdu: str) -> dict | None:
        """Decode PDU string data into structured payload."""
        try:
            pos = 0
            smsc_len = int(pdu[pos:pos+2], 16)
            pos += 2 + (smsc_len * 2)

            first_octet = int(pdu[pos:pos+2], 16)
            has_udh = bool(first_octet & 0x40)
            pos += 2

            addr_len = int(pdu[pos:pos+2], 16)
            pos += 2
            toa = pdu[pos:pos+2]
            pos += 2

            num_digits = addr_len + (1 if addr_len % 2 != 0 else 0)
            sender_hex = pdu[pos:pos+num_digits]
            pos += num_digits

            sender = ""
            for j in range(0, len(sender_hex), 2):
                if j + 1 < len(sender_hex):
                    sender += sender_hex[j+1] + sender_hex[j]
            sender = sender.rstrip("F").rstrip("f")
            if toa in ("91", "81") and not sender.startswith("+") and len(sender) > 5:
                sender = "+" + sender

            pos += 2
            dcs = int(pdu[pos:pos+2], 16)
            pos += 2

            ts_hex = pdu[pos:pos+14]
            pos += 14
            ts_rev = "".join([ts_hex[j+1] + ts_hex[j] for j in range(0, 14, 2)])
            formatted_time = f"{ts_rev[4:6]}.{ts_rev[2:4]}.20{ts_rev[0:2]} {ts_rev[6:8]}:{ts_rev[8:10]}:{ts_rev[10:12]}"

            udl = int(pdu[pos:pos+2], 16)
            pos += 2
            ud_hex = pdu[pos:]

            ref_id, total_parts, part_num = None, 1, 1
            data_bytes = bytes.fromhex(ud_hex)
            payload_bytes = data_bytes

            if has_udh and len(data_bytes) > 0:
                udh_len = data_bytes[0]
                if 1 + udh_len <= len(data_bytes):
                    udh = data_bytes[1:1+udh_len]
                    payload_bytes = data_bytes[1+udh_len:]

                    idx = 0
                    while idx + 1 < len(udh):
                        iei = udh[idx]
                        iedl = udh[idx+1]
                        if idx + 2 + iedl > len(udh):
                            break

                        if iei == 0x00 and iedl == 3:
                            ref_id = udh[idx+2]
                            total_parts = udh[idx+3]
                            part_num = udh[idx+4]
                        elif iei == 0x08 and iedl == 4:
                            ref_id = (udh[idx+2] << 8) | udh[idx+3]
                            total_parts = udh[idx+4]
                            part_num = udh[idx+5]
                        idx += 2 + iedl

            is_ucs2 = (dcs & 0x0C) == 0x08

            if is_ucs2:
                try:
                    body = payload_bytes.decode("utf-16be")
                except Exception:
                    body = payload_bytes.decode("latin1", errors="ignore")
            else:
                body = self._decode_gsm7(data_bytes, udl, has_udh)

            return {
                "sender": sender,
                "body": body,
                "timestamp": formatted_time,
                "ref_id": ref_id,
                "total_parts": total_parts,
                "part_num": part_num,
            }
        except Exception as e:
            _LOGGER.error("GL865T: PDU decode error: %s", e)
            return None

    def _decode_gsm7(self, data_bytes: bytes, udl: int, has_udh: bool) -> str:
        """Decode GSM 7-bit septets with Turkish national language shift support."""
        try:
            bit_offset = 0
            if has_udh and len(data_bytes) > 0:
                udh_len = data_bytes[0]
                total_udh_bytes = udh_len + 1
                bit_offset = total_udh_bytes * 8
                fill_bits = (7 - (bit_offset % 7)) % 7
                bit_offset += fill_bits

            num_septets = udl - (bit_offset // 7) if has_udh else udl

            unpacked_septets = []
            for j in range(int(num_septets)):
                start_bit = bit_offset + j * 7
                byte_idx = start_bit // 8
                bit_shift = start_bit % 8

                if byte_idx >= len(data_bytes):
                    break

                val = data_bytes[byte_idx] >> bit_shift
                if bit_shift > 0 and byte_idx + 1 < len(data_bytes):
                    val |= (data_bytes[byte_idx + 1] << (8 - bit_shift))

                unpacked_septets.append(val & 0x7F)

            gsm_basic = (
                "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞ\x1bÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
                "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
            )

            gsm_ext = {
                0x0A: "\n", 0x14: "^", 0x28: "{", 0x29: "}", 0x2F: "\\",
                0x3C: "[", 0x3D: "~", 0x3E: "]", 0x40: "|", 0x65: "€"
            }

            tr_shift = {
                0x63: "ç", 0x43: "Ç", 0x67: "ğ", 0x47: "Ğ",
                0x69: "ı", 0x49: "İ", 0x73: "ş", 0x53: "Ş"
            }

            chars = []
            escape_mode = False

            for val in unpacked_septets:
                if escape_mode:
                    if val in tr_shift:
                        chars.append(tr_shift[val])
                    elif val in gsm_ext:
                        chars.append(gsm_ext[val])
                    else:
                        chars.append(chr(val))
                    escape_mode = False
                    continue

                if val == 0x1B:
                    escape_mode = True
                else:
                    if val == 0x7E:
                        chars.append("ü")
                    elif val == 0x5E:
                        chars.append("Ü")
                    elif val == 0x7C:
                        chars.append("ö")
                    elif val == 0x5C:
                        chars.append("Ö")
                    elif val < len(gsm_basic):
                        chars.append(gsm_basic[val])
                    else:
                        chars.append(chr(val))

            return "".join(chars)
        except Exception as e:
            return f"[DECODE_ERR: {e}] " + data_bytes.decode("latin1", errors="ignore")
            
    def delete_all_read_sms(self) -> bool:
        """Deletes all read/processed SMS messages from SIM memory (AT+CMGD=1,4)."""
        with self.lock:
            ser = None
            try:
                ser = serial.Serial(self.port, self.baudrate, timeout=3)
                time.sleep(0.2)
                
                # First ensure PDU mode (or text mode) is set for command safety
                ser.write(b'AT+CMGF=0\r')
                time.sleep(0.2)
                ser.reset_input_buffer()

                # AT+CMGD=1,4 -> Delete all READ messages from SIM memory
                ser.write(b'AT+CMGD=1,4\r')
                time.sleep(0.5)

                response = ser.read_all().decode("latin1", errors="ignore")
                if "OK" in response:
                    _LOGGER.debug("GL865T: SIM card memory cleared successfully.")
                    return True
                else:
                    _LOGGER.warning("GL865T: Could not clear SIM memory, modem response: %s", response.strip())
                    return False
            except Exception as e:
                _LOGGER.error("GL865T: Error clearing SIM memory: %s", e)
                return False
            finally:
                if ser and ser.is_open:
                    ser.close()
