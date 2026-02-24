# URL Shortener

A URL shortening service that takes a URL as input and provides a shortened one back.

## Architecture

Three containerized services: nginx, Flask, and a PostgreSQL database. 

The nginx container serves a static HTML file and waits for a URL. After submitting the link, nginx proxies the request to the Flask container. Flask applies shortening logic, subsequently making a POST request to the shortening service and writing the shortened URL and its corresponding 
long link' to the PostgreSQL database. The user can click the shortened URL, where nginx again proxies the request to the Flask container, this time making a GET request to the PostgreSQL database. Shortened URLs do persist after container restarts via a Docker named volume.  

browser --> nginx --> Flask --> PostgreSQL --> back out to the user.

## Prerequisites

1. Install Docker Desktop and CLI

2. Clone the repo

- `git clone repo`
- `cd link-shortener`

## Environment Variables/Configuration

PostgreSQL requires credentials to work properly. You will need to create a .env file in the project directory, containing:
- POSTGRES_USER
- POSTGRES_PASSWORD
- POSTGRES_DB

A sample .env.example file is provided for your reference. 

## How to use

1. Build and run with `docker-compose up --build`

2. Visit http://localhost:80 in your browser to try

3. Press ctrl + c when done, followed by `docker-compose down -v`  

## Directory Tree
```
├── app
│   ├── app.py
│   ├── Dockerfile
│   ├── index.html
│   ├── nginx.conf
│   └── requirements.txt
├── docker-compose.yml
```
**Known Limitations**

- No HTTPS
- No rate limiting
- No input validation on submitted links
