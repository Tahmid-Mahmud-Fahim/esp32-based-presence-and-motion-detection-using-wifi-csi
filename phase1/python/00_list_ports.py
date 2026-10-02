from serial.tools import list_ports

ports = list(list_ports.comports())
if not ports:
    print("No serial ports found.")
else:
    for p in ports:
        print(f"{p.device:10s}  {p.description}  {p.hwid}")
