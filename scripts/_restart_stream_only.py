#!/usr/bin/env python3
import paramiko
c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('192.168.8.201', username='kioskuser', password='kiosk', timeout=12, allow_agent=False, look_for_keys=False)
_,o,_=c.exec_command("echo kiosk | sudo -S -p '' systemctl restart ha-kiosk-camera-stream.service", timeout=25, get_pty=True)
o.channel.settimeout(20)
try:
    print(o.read().decode()[-500:])
except Exception as e:
    print('read', e)
print('exit', o.channel.recv_exit_status())
c.close()
