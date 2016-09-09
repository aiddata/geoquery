/**
  * This is the controller for the root page, it is responsible for:
  *   - Managing sidebar tabs
  *   - Monitoring state change events and dispatching spinners and dialogs as
  *     needed
  */

angular.module('aiddataDET')
.controller('RootCtrl', function($scope, $rootScope, $log, $q, $state, $timeout, $mdDialog, info, queryFactory, spinFactory, modals, modalFactory) {
  console.log(modals);
  /*
   * ==================
   * Sidebar Management
   * ==================
   */
  $scope.sidebar = { open: false, active: '' };

  //  Handle request to open sidebar panel
  $rootScope.$on('sidebar:open', function(event, data) {
    $scope.sidebar.open = true;
    $scope.sidebar.active = data;
  });

  /*
   *  ===================
   *  State change events
   *  ===================
   */

  // When page content is loaded, open welcomeDialog if the user is landing on
  // the map page for the first time
  $scope.$on('$viewContentLoaded', function(event) {
    var stateName = _.get($state, '$current.self.name');

    if (stateName === "map" && !welcomeDialog.opened) {
      $mdDialog.show(welcomeDialog);
      welcomeDialog.opened = true;
    }

  });

  // Create spinner and dialogs when user begins to navigate to another page
  $rootScope.$on('$stateChangeStart', function(event, toState, toParams, fromState, fromParams, options) {
    // If user is going back to the map and will lose data, open map warning dialog
    if ( toState.name === 'map' &&
      queryFactory.querySize() &&
      !_.get(toParams, 'confirmation.confirmed') ) {

      // Cancel page change
      event.preventDefault();

      // Open dialog
      $mdDialog.show(returnToMap)
        .then(function() {
          // User clicks Ok
          queryFactory.resetQuery();
          $rootScope.$broadcast('query:updated');
          $state.go('map', { confirmation: { confirmed: true }});
          spinFactory.start();
        }, function () {
          // User clicks cancel
          spinFactory.stop();
        });
    } else {
      // If map warning dialog isn't needed
      spinFactory.start();
    }
  });

  // Stop spinner on successful loading of new page data
  $rootScope.$on('$stateChangeSuccess', function(event, toState, toParams, fromState, fromParams) {
    spinFactory.stop();
    $mdDialog.hide();
    $scope.sidebar.open = false;

    if (toState.name === 'requests' && toParams.notify) {
      $mdDialog.show(submittedDialog);
    }
  });

  /*
   * ==================
   * Dialog Definitions
   * ==================
   */

  // Return to Map Warning
  var returnToMap = modalFactory.confirm(modals.returnToMap);

  // Welcome Dialog
  var welcomeContent = _.extend(modals.welcome, info.welcome),
      welcomeDialog = modalFactory.dialog(welcomeContent);

// Submitted
  var submittedContent = _.extend(modals.submitted, info.submitted),
      submittedDialog = modalFactory.dialog(submittedContent);

});
