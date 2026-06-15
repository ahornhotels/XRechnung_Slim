@echo off
SET BASE=%~dp0..\..
SET NSSM=%BASE%\install\nssm.exe
SET SVCNAME=Suite8XRechnungSlim

"%NSSM%" stop "%SVCNAME%"
"%NSSM%" remove "%SVCNAME%" confirm
echo Service "%SVCNAME%" entfernt.
