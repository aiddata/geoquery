/**
  * These constant variables are used to set additional parameters for the dialogs
  * not directly returned from the API
  * the file each modal is dispached in is listed in parentheses
  *
  */

angular.module('aiddataDET')
  .constant('modals', {

    // Warning about data loss that opens when user returns to map with selections
    // in their cart (www/public_src/scripts/controllers/root.rootCtrl.js)
    returnToMap: {
      title: 'Are You Sure?',
      textContent: 'If you choose to navigate away from this page your data selection will be lost.',
      ok: 'Yes',
      cancel: 'No',
      clickOutsideToClose: true
    },

    // Welcome Greeting that opens when user first lands on map page
    // (www/public_src/scripts/controllers/root.rootCtrl.js)
    welcome: {
      ok: 'Get Started',
      clickOutsideToClose: true
    },

    // Limit Warning
    limitWarning: {
      title: 'Selection Limit Reached',
      content: 'The maximum number of selections is now in your cart, please checkout and create a new request to continue',
      ok: 'Proceed to checkout',
      cancel: 'Ok',
      clickOutsideToClose: true
    },
    //
    duplicateSelection: {
      title: 'This search is already in your cart'
    }
  });
