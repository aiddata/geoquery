/**
  * These constant variables are used to set additional parameters for the dialogs
  * not directly returned from the API
  * both are dispatched by the RootCtrl
  * (www/public_src/scripts/controllers/root.rootCtrl.js)
  */

angular.module('aiddataDET')
  .constant('modals', {

    // Warning about data loss that opens when user returns to map with selections
    // in their cart
    returnToMap: {
      title: 'Are You Sure?',
      textContent: 'If you choose to navigate away from this page your data selection will be lost.',
      ok: 'Yes',
      cancel: 'No',
      clickOutsideToClose: true
    },

    // Welcome Greeting that opens when user first lands on map page
    welcome: {
      ok: 'Get Started',
      clickOutsideToClose: true
    }
  });
