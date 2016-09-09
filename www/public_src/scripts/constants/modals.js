/**
  * These constant variables are used to set additional parameters for the dialogs
  * not directly returned from the API
  * the file each modal is dispached in is listed in parentheses
  *
  */

angular.module('aiddataDET')
  .constant('modals', {

    // Return to Map Warning
    // in their cart (www/public_src/scripts/controllers/root.rootCtrl.js)
    returnToMap: {
      title: 'Are You Sure?',
      textContent: 'If you choose to navigate away from this page your data selection will be lost.',
      ok: 'Yes',
      cancel: 'No',
      clickOutsideToClose: true,
      name: 'Return to Map Warning'
    },

    // Welcome Greeting
    // (www/public_src/scripts/controllers/root.rootCtrl.js)
    welcome: {
      // title: SET BY API,
      // content: SET BY API,
      ok: 'Get Started',
      clickOutsideToClose: true,
      name: 'Welcome Greeting'
    },

    // Request Submitted Notification
    // (www/public_src/scripts/controllers/root.rootCtrl.js)
    submitted: {
      // title: SET BY API,
      // content: SET BY API,
      clickOutsideToClose: true,
      ok: 'Ok',
      name: 'Request Submitted Notification'
    },

    // Limit Warning
    // (www/public_src/scripts/controllers/search.selectionTextCtrl.js)
    limitWarning: {
      title: 'Selection Limit Reached',
      textContent: 'The maximum number of selections is now in your cart, please checkout and create a new request to continue',
      ok: 'Proceed to checkout',
      cancel: 'Ok',
      clickOutsideToClose: true,
      name: 'Limit Warning'
    },

    // Duplicate Selection Warning
    // (www/public_src/scripts/controllers/search.selectionTextCtrl.js)
    duplicateSelection: {
      message: 'This search is already in your cart',
      name: 'Duplicate Selection Warning'
    },

    // Submission Error
    // (www/public_src/scripts/controllers/search.selectionTextCtrl.js)
    submissionError: {
      message: 'There was an error submitting your request',
      name: 'Submission Error'
    },

    // Empty Request Warning
    // (www/public_src/scripts/controllers/checkout.selections.js)
    emptyRequest: {
      clickOutsideToClose: true,
      title: 'Are you sure you want to remove this selection?',
      textContent: 'Your cart will be empty',
      ok: 'Return to search',
      cancel: 'Cancel',
      name: 'Empty Request Warning'
    }
  });
