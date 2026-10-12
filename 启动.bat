@echo off
chcp 65001 >nul
title 联邦医院知识图谱AI 启动器
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0launcher.ps1"
exit
