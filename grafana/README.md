# Grafana Dashboard

This directory contains a proof-of-concept Grafana dashboard to experiment with.

![Screenshot of Grafana Dashboard](/grafana/dashboard-screenshot.png)

## Setting up Grafana locally

Here's how to get Grafana up-and-running locally with podman, alongside our usual PostgreSQL server so that they can talk to each other

1. Remove the current PostgreSQL container, if it exists
2. **cd to this directory**
3. Create a pod for our two servers with `podman pod create -p 3000:3000 -p 5432:5432 geoquery`
   This will expose port 3000 for Grafana and 5432 for PostgreSQL to your local machine
4. Add the PostgreSQL container to your pod with `podman run --pod geoquery -e POSTGRES_PASSWORD=mysecretpassword -d docker.io/postgis/postgis:16-3.4-alpine`
5. Add the Grafana container to your pod with `podman run -d --pod geoquery grafana/grafana-oss`
6. Add the Loki container to your pod with `podman run -d --pod geoquery -v ./loki-config.yaml:/etc/loki/local-config.yaml:Z grafana/loki:latest`
7. Add the promtail container to your pod with `podman run -d --pod geoquery -v ../logs:/var/log:Z -v ./promtail-config.yaml:/etc/promtail/config.yml:Z grafana/promtail:latest`
8. Re-initialize the PostgreSQL server using the usual instructions at the root of this repo
9. Navigate to http://localhost:3000 in your browser, and login with username admin, password admin
10. Click on Add a Data Source, and scroll down to PostgreSQL. Here are the connection options for PostgreSQL:
   - Host: localhost:5432
   - Database: postgres
   - User: postgres
   - User: postgres Password: mysecretpassword
   - TLS/SSL Mode: disable
   At the bottom of the page, click Save and Test
11. Add another Data Source: Loki
   - Connection URL: http://localhost:3100
   At the bottom of the page, click Save and Test
12. Save and test the PostgreSQL connection, making sure it is successful
13. Go back home, and click on New Dashboard
14. Click on Import dashboard
15. Paste in the JSON found in `dashboard.json` in this directory
16. Open the new dashboard and see it in action! If everything went well it should look like the screenshot above
