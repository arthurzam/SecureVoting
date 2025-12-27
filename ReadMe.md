An active demo can be found at https://securevoting.ddns.net/.

# Running the demo

This demo requires the `docker` engine and the `docker-compose` tool to be installed.

You can install Docker by following the instructions on the [official Docker website](https://docs.docker.com/get-docker/).

To install `docker-compose`, follow the instructions on the [official Docker Compose website](https://docs.docker.com/compose/install/).

Once you have Docker and Docker Compose installed, you can proceed with the following steps.

## Generating TLS keys

Requires `openssl` to run this script. You can install it using your package manager. For example, on Ubuntu:

```shell
sudo apt-get install openssl
```

Run:

```shell
cd keys
./generate.sh avote{1..3}
```

## Environment Variables

The following environment variables need to be set in the `.env` file:

- `TALLIERS_EXTERNAL`: Represents the external talliers addresses, used for filling addresses into the HTML template.
- `TALLIERS_INTERNAL`: Represents the internal talliers addresses (inside the `docker` network).
- `WEBSITE_URL`: The website URL of the demo (used in the emails sent to voters).
- `MAIL_DISABLED`: Boolean (zero or one), representing if mail sending should be disabled.
- `GMAIL_USER`: In case email is enabled, the Gmail username.
- `GMAIL_PASSWORD`: In case email is enabled, the Gmail password. Created through App Password in Google account settings.

Example:

```shell
TALLIERS_EXTERNAL="ws://localhost:8080|ws://localhost:8081|ws://localhost:8082"
TALLIERS_INTERNAL="avote1:18080|avote2:18080|avote3:18080"

WEBSITE_URL="http://localhost"

MAIL_DISABLED=1

GMAIL_USER="<username>"
GMAIL_PASSWORD="<password>"
EMAIL_ADDRESS="${GMAIL_USER}@gmail.com"
```

## Running the demo

In the root directory, run:

```shell
docker compose up -d
```

This command will start all the services defined in the `docker-compose.yml` file in detached mode.

To stop the services, run:

```shell
docker compose down
```
