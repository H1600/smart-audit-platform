#!/usr/bin/env python3
"""检查服务器 Python 3.10 环境"""
import paramiko
s = paramiko.SSHClient()
s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
s.connect("8.138.253.56", 22, "root", "HjH181600", timeout=15)
def run(cmd, t=15):
    i,o,e = s.exec_command(cmd, timeout=t)
    ec = o.channel.recv_exit_status()
    return o.read().decode(errors="replace").strip(), e.read().decode(errors="replace").strip(), ec

# Check Python 3.10
for ver_cmd in ["python3.10 --version", "/usr/bin/python3.10 --version", "/usr/local/bin/python3.10 --version", "conda run -n base python --version 2>/dev/null"]:
    o,_,ec = run(ver_cmd, 10)
    if ec == 0:
        print(f"✅ Found: {ver_cmd} -> {o}")
        break
else:
    print("❌ Python 3.10 not found")

# Check pip
o,_,_ = run("python3.10 -m pip --version 2>/dev/null || pip3.10 --version 2>/dev/null || echo 'no pip'", 10)
print(f"pip: {o}")

# Check project directory
o,_,_ = run("ls /opt/smart-audit-platform/ 2>/dev/null || echo 'not found'", 10)
print(f"Project dir: {o[:200]}")

# Check disk space
o,_,_ = run("df -h / | tail -1", 10)
print(f"Disk: {o}")

# Check memory
o,_,_ = run("free -h | grep Mem", 10)
print(f"Memory: {o}")

s.close()
