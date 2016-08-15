angular.module('aiddataDET')
.controller('RootCtrl', function($scope, $rootScope, $log, $q, $state, $timeout, $mdDialog, language, queryFactory, spinFactory) {

  $scope.sidebar = { open: false, active: '' };

  $rootScope.$on('sidebar:open', function(event, data) {
    $scope.sidebar.open = true;
    $scope.sidebar.active = data;
  });

  $rootScope.$on('$stateChangeError', function(event, toState, toParams, fromState, fromParams, error) {
    $log.error(event, toState, toParams, fromState, fromParams, error);
    spinFactory.stop();
  });

  $rootScope.$on('$stateChangeSuccess', function(event, toState, toParams, fromState, fromParams) {
    spinFactory.stop();
    $mdDialog.hide();
    $scope.sidebar.open = false;
  });

  $scope.$on('$viewContentLoaded', function(event) {
    if ($state.$current.self.name === "map" && !welcomeDialog.opened) {
      $mdDialog.show(welcomeDialog);
      welcomeDialog.opened = true;
    }
  });

  $rootScope.$on('$stateChangeStart', function(event, toState, toParams, fromState, fromParams, options) {
    spinFactory.start();
    if ( toState.name === 'map' &&
      queryFactory.querySize() &&
      !_.get(toParams, 'confirmation.confirmed') ) {
      event.preventDefault();

      $mdDialog.show(returnToMap).then(function() {
        queryFactory.resetQuery();
        $rootScope.$broadcast('query:updated');
        $state.go('map', { confirmation: { confirmed: true }});
        spinFactory.start();
      });
    }
  });

  /* Modal Definitions */
  var returnToMap = $mdDialog.confirm()
    .clickOutsideToClose(true)
    .title("Are You Sure?")
    .textContent("If you choose to navigate away from this page your data selection will be lost.")
    .ok('Yes')
    .cancel('No');

  var welcomeDialog = $mdDialog.alert()
    .clickOutsideToClose(true)
    .title(language.welcome.title)
    .textContent(language.welcome.content)
    .ok('Get Started');

});
