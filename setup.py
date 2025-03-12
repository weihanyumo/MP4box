from cx_Freeze import setup, Executable

setup(
    name="mp4Par",
    version="1.0",
    description="Your Python application",
    executables=[Executable("parseMp4.py")]
)
