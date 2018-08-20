FROM python:3.7-slim

WORKDIR /app

ADD . /app

RUN pip install --trusted-host pypi.python.org -r requirements.txt

RUN apt-get update && apt-get install -y \
    libopus0 \
    ffmpeg

ENV NAME World

CMD ["python", "main.py"]