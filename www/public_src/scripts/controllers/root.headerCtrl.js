angular.module('aiddataDET')
.controller('HeaderCtrl', function($scope, $rootScope, $log, $stateParams, $state, $mdDialog, queryFactory, spinFactory, language) {

  $scope.currentStep = $state;
  $scope.queryLen = 0;

  $scope.tabs = {
    options:  {
      cart: { text: 'View Cart', icon: 'fa-shopping-cart' },
      help: { text: 'Help', icon: 'fa-question-circle' },
      previousRequests: { text: 'View Past Requests', icon: 'fa-history' }
    },
    order: ['cart', 'previousRequests', 'help']
  };

  $scope.activate = function (tab) {
    $scope.sidebarOpen = true;
    $rootScope.$broadcast('sidebar:open', tab);
  };

  $rootScope.$on('query:updated', function() {
    $scope.queryLen = queryFactory.querySize();
  });

  $rootScope.$on('$viewContentLoaded', function(event) {
    $scope.currentStep = $state.current.name;
  });

});
