angular.module('aiddataDET')
.controller('HeaderCtrl', function($scope, $rootScope, $log, $stateParams, $state, $mdDialog, queryFactory, spinFactory) {
  $scope.currentStep = $state;
  console.log($state);
  $scope.queryLen = 0;

  $scope.tabs = {
    options:  {
      cart: { active: false, text: 'View Cart', icon: 'fa-shopping-cart' },
      help: { active: false, text: 'Help', icon: 'fa-question-circle' },
      previousRequests: { active: false, text: 'View Past Requests', icon: 'fa-history' }
    },
    order: ['cart', 'previousRequests', 'help']
  };

  // @TODO: Should move this to an alert directive or factory
  var welcomeModal = $mdDialog.alert()
    .clickOutsideToClose(true)
    .title("Welcome to the Data Extraction Tool by AidData!")
    .textContent('Allowing YOU to extend a helping hand...')
    .ok('Get Started');

  $scope.activate = function (tab) {
    _.each($scope.tabs, function(t) { t.active = false; });
    tab.active = true;
  };

  $rootScope.$on('query:updated', function(event, data) {
    $scope.queryLen = queryFactory.querySize();
  });

  $rootScope.$on('$stateChangeStart', function(event, toState, toParams, fromState, fromParams, options) {
    spinFactory.start();
  });

  $rootScope.$on('$stateChangeError', function(event, toState, toParams, fromState, fromParams, error) {
    console.log(event, toState, toParams, fromState, fromParams, error);
    spinFactory.stop();
  });

  $rootScope.$on('$stateChangeSuccess', function(event, toState, toParams, fromState, fromParams) {
    spinFactory.stop();
  });

  $scope.$on('$viewContentLoaded', function(event) {
    $scope.currentStep = $state.current.name;

    if ($scope.currentStep === "map" && !welcomeModal.visible) {
      $mdDialog.show(welcomeModal);
      welcomeModal.visible = true;
    }
  });

});
