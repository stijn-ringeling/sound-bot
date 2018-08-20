FROM python:3.7-slim

WORKDIR /app

ADD . /app

RUN pip insall --trusted-host pypi.python.org -r requirements.txt

ENV NAME World

CMD ["python", "main.py"]