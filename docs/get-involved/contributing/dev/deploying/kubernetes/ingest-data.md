# Ingest Data

This guide will walk through the process of ingesting dataset and feature data using the Geoquery backend on Kubernetes.

## Adding Datasets

1. Add the desired ingest script to an ingest folder in your workbench pod within your kubernetes namespace. Currently available ingest scripts can be found in [this folder](https://github.com/aiddata/geoquery-update/tree/cmhwang/ingest/datasets) within the geoquery update repository.  

2. Add the corresponding ingest json from the [geo-datasets GitHub repository](https://github.com/aiddata/geo-datasets/tree/master/datasets). Each datasets's ingest json can be found within the dataset's folder.

    #### Debug Tips
    - You may need to edit a couple variables within the json: 
        - Update the path in the json to match the volume path within kubernetes. The default path to the volume hosting the data from your root folder is `/geo-datasets/data/rasters/`.
        - Rename the vairable bas path (if it exists) t0 title_path.
        - Add is_global as a variable (if it doesn't already exist) and set it to true.
    - Depending on the setting of your namespace, you may need to manually make the ouput file in the json.

3. In you root folder run this python command: `python /geoquery/ingest/datasets/_.py`

4. Enter any postgis pod in your namespace and run the command `psql -d geoquery` to enter your database. From here you can check whether the datasets have been ingested. 