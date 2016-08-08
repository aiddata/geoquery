angular.module('aiddataDET')
.controller('HeaderCtrl', function($scope, $rootScope, $log, $stateParams, $state, $mdDialog, queryFactory, spinFactory) {

  var returnToMap = $mdDialog.confirm()
    .clickOutsideToClose(true)
    .title("This will clear your search")
    .ok('ok')
    .cancel('cancel');

  var welcomeDialog = $mdDialog.alert()
    .clickOutsideToClose(true)
    .title("Welcome to the Data Extraction Tool by AidData!")
    .textContent('Allowing YOU to extend a helping hand...')
    .ok('Get Started');

  $scope.currentStep = $state;
  $scope.queryLen = 0;

  $scope.tabs = {
    options:  {
      cart: { active: false, text: 'View Cart', icon: 'fa-shopping-cart' },
      help: { active: false, text: 'Help', icon: 'fa-question-circle' },
      previousRequests: { active: false, text: 'View Past Requests', icon: 'fa-history' }
    },
    order: ['cart', 'previousRequests', 'help']
  };

  $scope.activate = function (tab) {
    _.each($scope.tabs, function(t) { t.active = false; });
    tab.active = true;
  };

  $rootScope.$on('query:updated', function() {
    $scope.queryLen = queryFactory.querySize();
  });

  $rootScope.$on('$stateChangeStart', function(event, toState, toParams, fromState, fromParams, options) {
    if (
        toState.name === 'map' &&
        $scope.queryLen &&
        !_.get(toParams, 'confirmation.confirmed')
    ) {
      event.preventDefault();

      $mdDialog.show(returnToMap).then(function() {
        queryFactory.resetQuery();
        $rootScope.$broadcast('query:updated');
        $state.go('map', { confirmation: { confirmed: true }});
        spinFactory.start();
      });
    }
  });

  $rootScope.$on('$stateChangeError', function(event, toState, toParams, fromState, fromParams, error) {
    $log.error(event, toState, toParams, fromState, fromParams, error);
    spinFactory.stop();
  });

  $rootScope.$on('$stateChangeSuccess', function(event, toState, toParams, fromState, fromParams) {
    spinFactory.stop();
    $mdDialog.hide();
    _.each($scope.tabs.options, function(option) {
      option.active = false;
    });
  });

  $scope.$on('$viewContentLoaded', function(event) {
    $scope.currentStep = $state.current.name;

    if ($scope.currentStep === "map" && !welcomeDialog.opened) {
      $mdDialog.show(welcomeDialog);
      welcomeDialog.opened = true;
    }
  });

});
