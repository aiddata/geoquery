# Grafana Dashboard

This directory contains a proof-of-concept Grafana dashboard to experiment with.

![Screenshot of Grafana Dashboard](/grafana/dashboard-screenshot.png)

## Setting up Grafana locally

Here's how to get Grafana up-and-running locally with podman, alongside our usual PostgreSQL server so that they can talk to each other

1. Remove the current PostgreSQL container, if it exists
2. Create a pod for our two servers with `podman pod create -p 3000:3000 -p 5432:5432 geoquery`
   This will expose port 3000 for Grafana and 5432 for PostgreSQL to your local machine
3. Add the PostgreSQL container to your pod with `podman run --pod geoquery -e POSTGRES_PASSWORD=mysecretpassword -d docker.io/postgis/postgis:16-3.4-alpine`
4. Add the Grafana container to your pod with `podman run -d --pod geoquery grafana/grafana-oss`
5. Re-initialize the PostgreSQL server using the usual instructions at the root of this repo
6. Navigate to http://localhost:3000 in your browser, and login with username admin, password admin
7. Click on Add a Data Source, and scroll down to PostgreSQL. Here are the connection options for PostgreSQL:
   - Host: localhost:5432
   - Database: postgres
   - User: postgres
   - User: postgres Password: mysecretpassword
   - TLS/SSL Mode: disable
8. Save and test the PostgreSQL connection, making sure it is successful
9. Go back home, and click on New Dashboard
10. Click on Import dashboard
11. Paste in the JSON found in `dashboard.json` in this directory
12. Open the new dashboard and see it in action! If everything went well it should look like the screenshot above
