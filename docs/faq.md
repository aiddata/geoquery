# Frequently Asked Questions

## Getting started

### Do I need an account?
No. You can submit a request with just an email address. Signing in with GitHub keeps all your requests in one place. See [Accounts and request history](https://docs.geoquery.org/using-geoquery/accounts/).

### Can I use my own boundary files?
Coming soon. You'll be able to upload your own boundaries as a GeoJSON file (`.geojson` or `.json`, up to 50 MB) from the "Custom" tab on the GeoQuery boundary selection page.

### Can I select data for multiple boundaries?
Yes, you can select as many feature collections at a time as you like (e.g., Ghana ADM1, Ghana ADM2, Tanzania ADM1), but individual feature selection is only available within a single feature collection (e.g., Ghana ADM1). Each collection is kept separate: every feature gets its own row in your results, labelled with its collection, so overlapping selections such as Ghana ADM1 and Ghana ADM2 are not combined or intersected.

### Do GeoQuery's boundaries reflect AidData's position on borders?
No. Boundaries, names and labels are shown as published by their providers, such as geoBoundaries, and do not imply any opinion by AidData or William & Mary on the legal status of any area or its borders. See the [map disclaimer](https://docs.geoquery.org/data_documentation/map-disclaimer/).

### Can I edit or resubmit a previous request?
Modifying previous requests is not currently supported. You can submit a new request at any time, and any previously cached data will be returned quickly without reprocessing.

### How do I find a request I made earlier?
Sign in and open **Past Requests**. Without an account, open **Past Requests**, enter the email address you used, and we'll email you a link to your request history. Requests made on earlier versions of GeoQuery are included.

---

## Data and results

### What format will I receive my data in?
Each completed request is a zip file that includes:

- A **CSV** file containing your results for use in Excel, Stata, SPSS, R, and similar tools.
- An **HTML** file with metadata for your request including dataset descriptions, citation information, and sources.
- A **GeoPackage** file of your areas' boundaries for use with GIS software.
- A **PDF** file of the publication describing GeoQuery's underlying methods, which must be cited when using data from GeoQuery. See also [Citing GeoQuery](https://docs.geoquery.org/citing/).
- A **JSON** file with the raw contents of your request selection (not typically needed but may help with programmatic management of data).

### How do I read the results file?
Each row is one area, and each column is one value you asked for, such as a dataset's mean for a given year. An empty cell means the dataset has no data for that area. See [Using your results](https://docs.geoquery.org/using-geoquery/results/) for the details, and for how to join the results to the boundaries in GIS software.

### How long will it take to receive my data?
Many requests complete almost instantly due to preprocessing and caching. Requests requiring new processing may take up to several hours.

### How long are my results kept?
Your results stay available to download from your request's page, and from your request history.

### Are there limits on how much I can request?
There's no limit on the number of boundaries or datasets in a request. To keep GeoQuery available to everyone, each connection can submit up to 60 requests an hour.

### Can I reuse and share the data?
Yes, within each dataset's license. The datasets come from third-party providers, and each has its own license and citation. You'll find them in the [data documentation](https://docs.geoquery.org/data_documentation/datasets/) and in the documentation file delivered with your results.

### Why are some years missing from the options for a dataset?
Filters are dynamically generated from the underlying data. Some datasets simply do not have records for every year.

### Where can I find details on the extract methods used?
The tooltips alongside each method in the selection tabs describe the extract methods. You can also read the GeoQuery paper included with your results, or the [GeoQuery source code](https://github.com/aiddata/geoquery).

---

## Research and examples

### Do you have examples of analyses conducted using GeoQuery data?
Yes. Examples of reports and publications using GeoQuery across a range of disciplines and research topics are on the [Research and Use Cases](https://docs.geoquery.org/using-geoquery/research-and-use-cases/) page.

### Do you conduct research using this tool?
Yes. AidData works with a wide range of organizations to analyze spatial information. See examples at [aiddata.org/geoquery](https://www.aiddata.org/geoquery) or contact us at [geo@aiddata.wm.edu](mailto:geo@aiddata.wm.edu) to learn more about specific workstreams at AidData.

---

## Support and feedback

### Do you have tutorials or additional learning resources?
Yes. Tutorials are in the [documentation](https://docs.geoquery.org/using-geoquery/tutorials/), and videos and research applications are at [aiddata.org/geoquery](https://www.aiddata.org/geoquery).

### How can I get help or ask a question?
We suggest first exploring the rest of the documentation, as well as the GitHub repository for existing Issues or Discussions. If you still need help, you may create a new Issue in [our GitHub repository](https://github.com/aiddata/geoquery) or email us at [geo@aiddata.wm.edu](mailto:geo@aiddata.wm.edu).

### Where can I provide feedback or request new datasets?
You may submit specific feedback (bugs, suggested features, etc) or data requests by creating a new Issue in our [GitHub repository](https://github.com/aiddata/geoquery). For any other feedback please email us at [geo@aiddata.wm.edu](mailto:geo@aiddata.wm.edu).

### Is GeoQuery accessible?
We aim to meet WCAG 2.2 AA, and are working through some known gaps. See the [accessibility statement](https://docs.geoquery.org/accessibility/), and tell us at [geo@aiddata.wm.edu](mailto:geo@aiddata.wm.edu) if something is hard to use.

### How is my information used?
See the [Privacy Policy](https://docs.geoquery.org/privacy/) and [Terms of Use](https://docs.geoquery.org/terms/).

### How can I support GeoQuery?
GeoQuery is a free service, but continued development and hosting depends on funding. If you are a funder or donor interested in helping us help others, please reach out to our partnerships team at [awooley@aiddata.org](mailto:awooley@aiddata.org).
