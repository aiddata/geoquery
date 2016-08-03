angular.module('aiddataDET')
.controller('HeaderCtrl', function($scope, $rootScope, $log, $stateParams, $state, queryFactory, spinFactory) {
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

  $rootScope.$on('query:updated', function(event, data) {
    $scope.queryLen = queryFactory.querySize();
  });

  $rootScope.$on('$stateChangeStart', function(event, toState, toParams, fromState, fromParams, options) {
    spinFactory.start();
    $log.debug(event, toState, toParams, fromState, fromParams, options);
  });

  $rootScope.$on('$stateChangeError', function(event, toState, toParams, fromState, fromParams, error) {
    spinFactory.stop();
    $log.error(event, toState, toParams, fromState, fromParams, error);
  });

  $rootScope.$on('$stateChangeSuccess', function(event, toState, toParams, fromState, fromParams) {
    spinFactory.stop();
    $scope.currentStep = toState;
  });

});
