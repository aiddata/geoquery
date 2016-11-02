/**
  * These constant variables are used to set the configuration for the site,
  * they are referenced in the site's headers (www/public/index.html)
  */

angular.module('aiddataDET')
  .constant('config', {

    // Header Config
    pageTitle: 'AidData geo(query)',
    faviconUrl: 'http://www.aiddata.org/sites/all/themes/aiddata/favicon.ico',
    meta: {
      description: 'this is the description',
      keywords: 'aiddata,geo,query,keywords'
    },
    googleTrackingID: 'UA-83421297-1',

    // Brand
    logoUrl: 'http://aiddata.org/sites/all/themes/aiddata/logo.png',

    // Domain
    domain: 'aiddata'
  });
