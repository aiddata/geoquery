---
description: "Answers to common questions about GeoQuery: accounts, boundaries, datasets, results, turnaround times, limits, sharing and support."
---

# Frequently Asked Questions

## Getting started

### Do I need an account?
No. You can submit a request with just an email address. Signing in with GitHub keeps all your requests in one place. See [Accounts and request history](using-geoquery/accounts.md).

### What is a feature?
A feature is one area in a boundary set, such as a single district in Ghana ADM2 or a single province in Kenya ADM1. Your results have one row for each feature you select.

### Can I use my own boundary files?
Coming soon. You'll be able to upload your own boundaries as a GeoJSON file (`.geojson` or `.json`, up to 50 MB) with the **Custom upload** button above the boundary search.

### Can I select data for multiple boundaries?
Yes. You can select as many boundary sets as you like, such as Ghana ADM1, Ghana ADM2 and Tanzania ADM1, and **Bulk select** lets you tick whole levels at once. Selecting individual features on the map works within one boundary set at a time. Each boundary set is kept separate in your results; see [Selecting multiple boundary sets](using-geoquery/multiple-boundaries.md).

### Why don't I see a dataset I expected?
GeoQuery only lists datasets that have data for the boundaries you've selected, so a regional dataset doesn't appear for boundaries outside its region. Each dataset's page in the [data documentation](data_documentation/datasets/index.md) describes where and when it has data. See [Dataset coverage](using-geoquery/getting-started.md#dataset-coverage).

### Do GeoQuery's boundaries reflect AidData's position on borders?
No. Boundaries, names and labels are shown as published by their providers, such as geoBoundaries, and do not imply any opinion by AidData or William & Mary on the legal status of any area or its borders. See the [map disclaimer](data_documentation/map-disclaimer.md).

### Can I edit or resubmit a previous request?
A submitted request can't be changed, but you can build a new one from it. Open the request's page and choose **Duplicate request** › **Open in a new tab**: its boundaries, datasets and options are loaded for you to change and submit. Data that has already been processed is returned quickly. See [Starting from a past request](using-geoquery/getting-started.md#starting-from-a-past-request).

### Can I share a request with someone?
Yes. **Copy share link**, at the bottom of the panel, copies a link to the request you're building; anyone who opens it gets their own copy to change and submit. Once a request is submitted, **Copy results link** on its page copies a link anyone can use to open the page and download the results. See [Sharing a request](using-geoquery/getting-started.md#sharing-a-request).

### How do I find a request I made earlier?
Signed in, open **My Requests** in the **Account** menu. Without an account, open **Past Requests** in the same menu, enter the email address you used, and we'll email you a link to your request history. Requests made on earlier versions of GeoQuery are included.

---

## Data and results

### What format will I receive my data in?
A zip file with your results as a CSV for Excel, Stata, SPSS, R and similar tools, your features' boundaries as a GeoPackage for GIS software, a documentation file with each dataset's source, license and citation, and the paper describing GeoQuery's methods. See [Using your results](using-geoquery/results.md) for the full list and how to read them.

### How do I read the results file?
Each row is one feature, and each column is one value you asked for, such as a dataset's mean for a given year. An empty cell means the dataset has no data for that area. See [Using your results](using-geoquery/results.md) for the details, and for how to join the results to the boundaries in GIS software.

### How long will it take to receive my data?
Many requests complete almost instantly, because GeoQuery keeps data it has already processed. Requests that need new processing, particularly large areas or many features, may take up to several hours. The [System Status](using-geoquery/system-status.md) page shows how busy GeoQuery is right now.

### What do the request statuses mean?
See [Checking on a request](using-geoquery/accounts.md#checking-on-a-request).

### How long are my results kept?
Your results stay available to download from your request's page, and from your request history.

### Are there limits on how much I can request?
There's no limit on the number of boundaries or datasets in a request. To keep GeoQuery available to everyone, each connection can submit up to 60 requests an hour.

### Can I reuse and share the data?
Yes, within each dataset's license. The datasets come from third-party providers, and each has its own license and citation. You'll find them in the [data documentation](data_documentation/datasets/index.md) and in the documentation file delivered with your results.

### Why are some years missing from the options for a dataset?
The options come from the data itself, and some datasets don't have data for every year.

### Where can I find details on the extract methods used?
On the Customize page, the ⓘ icon beside each measure describes it. You can also read the GeoQuery paper included with your results, or the [GeoQuery source code](https://github.com/aiddata/geoquery).

### Can I get GeoQuery data with code?
Yes. GeoQuery has a public API and a STAC API for finding datasets and boundaries, and a stats API for its usage figures. See [API access](using-geoquery/api.md).

---

## Research and examples

### Do you have examples of analyses conducted using GeoQuery data?
Yes. Examples of reports and publications using GeoQuery across a range of disciplines and research topics are on the [Research and Use Cases](using-geoquery/research-and-use-cases.md) page.

### Do you conduct research using this tool?
Yes. AidData works with a wide range of organizations to analyze spatial information. See examples at [aiddata.org/geoquery](https://www.aiddata.org/geoquery) or contact us at [geo@aiddata.wm.edu](mailto:geo@aiddata.wm.edu) to learn more about specific workstreams at AidData.

---

## Support and feedback

### Do you have tutorials or additional learning resources?
Yes. Worked examples are under [Tutorials](using-geoquery/tutorials/index.md), and videos and research applications are at [aiddata.org/geoquery](https://www.aiddata.org/geoquery).

### How can I get help or ask a question?
We suggest first exploring the rest of the documentation, as well as the GitHub repository for existing Issues or Discussions. If you still need help, you may create a new Issue in [our GitHub repository](https://github.com/aiddata/geoquery) or email us at [geo@aiddata.wm.edu](mailto:geo@aiddata.wm.edu).

### Where can I provide feedback or request new datasets?
You may submit specific feedback (bugs, suggested features, etc) or data requests by creating a new Issue in our [GitHub repository](https://github.com/aiddata/geoquery). For any other feedback please email us at [geo@aiddata.wm.edu](mailto:geo@aiddata.wm.edu).

### Is GeoQuery accessible?
We aim to meet WCAG 2.2 AA, and are working through some known gaps. See the [accessibility statement](accessibility.md), and tell us at [geo@aiddata.wm.edu](mailto:geo@aiddata.wm.edu) if something is hard to use.

### How is my information used?
See the [Privacy Policy](privacy.md) and [Terms of Use](terms.md).

### How can I support GeoQuery?
GeoQuery is a free service, but continued development and hosting depends on funding. If you are a funder or donor interested in helping us help others, please reach out to our partnerships team at [awooley@aiddata.org](mailto:awooley@aiddata.org).
