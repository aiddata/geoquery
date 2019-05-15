/**
  * These constant variables are used to set the configuration for the site,
  * they are referenced in the site's headers (www/public/index.html)
  */

angular.module('aiddataDET')
  .constant('config', {

    // Header Config
    pageTitle: 'AidData GeoQuery',
    faviconUrl: 'http://geo.aiddata.org/assets/favicon.png',
    meta: {
      description: 'GeoQuery enables individuals and organizations of all skill levels to freely find and aggregate satellite, economic, health, conflict, and other spatial data into a single, simple-to-use file compatible with Microsoft Excel and other common software.',
      keywords: 'aiddata,geo,query,geoquery,geospatial,aid,satellite,data,gis'
    },
    googleTrackingID: 'UA-86742618-1',

    // Brand
    logoUrl: 'http://geo.aiddata.org/assets/aid_data.png',
    // Domain
    domain: 'aiddata'
  });
