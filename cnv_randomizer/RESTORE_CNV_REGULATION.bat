@echo off
cd /d "%~dp0\..\.."
echo Restoring CNV 3.0 regulation.bin (2968720 bytes)...
copy /Y "mod\regulation.bin.pre_cnv_rand_42001.bak" "mod\regulation.bin"
for %%F in ("mod\regulation.bin") do echo Size: %%~zF bytes
if %%~zF==2968720 (
    echo OK - pure CNV bin restored.
) else (
    echo WARNING - size not 2968720. Use your CNV zip regulation.bin.
)
pause
