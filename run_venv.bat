
:: Batch script to setup a virtual development environment

@echo off

:: Variables
set venv_folder=.\.venv
set script_name=main.py 


if exist %venv_folder%\ (
    echo Virtual environment already exists
    echo.
    goto activate
) else (
    :: Creating virtual environment
    echo Creating virtual environment
    echo.

    c:\Users\Vovik\AppData\Local\Programs\Python\Python311\python.exe  -m venv "%venv_folder%"
    call %venv_folder%\Scripts\activate.bat
    :: Update pip
    echo Updating pip in virtual environment
    echo.
    python.exe -m pip install --upgrade pip

    echo Install requirements.txt in virtual environment
    %venv_folder%\Scripts\pip install -r requirements.txt
    rem echo Install Pytorch
    rem pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
    rem echo flash_attn install 
    rem pip  wheel
    rem pip install flash_attn  --no-build-isolation


)

:: Activating virtual environment
:activate
echo Activating virtual environment
echo.

call %venv_folder%\Scripts\activate.bat

:end
.\.venv\Scripts\python.exe "%script_name%"

pause
timeout 5