# watashi v12.3.40dev: the old project name was taken out of this file (names, paths and links only)
FROM python:3.7-alpine
COPY . /app
WORKDIR /app
RUN pip install .
RUN watashipanel create-db
RUN watashipanel populate-db
RUN watashipanel add-user -u admin -p admin
EXPOSE 5000
CMD ["watashipanel", "run"]
