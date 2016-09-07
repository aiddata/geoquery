/**
  * These constant variables are used to set the configuration for the site,
  * they are referenced in the site's headers (www/public/index.html)
  */

angular.module('aiddataDET')
  .constant('config', {

    // Header Config
    pageTitle: 'AidData Data Extraction Tool',
    faviconUrl: 'http://www.aiddata.org/sites/all/themes/aiddata/favicon.ico',
    meta: {
      description: 'this is the description',
      keywords: 'these,are,some,keywords'
    }
  });
