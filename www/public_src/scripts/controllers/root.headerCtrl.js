angular.module('aiddataDET')
.controller('HeaderCtrl', function($scope, $rootScope, $log, $stateParams, $state, $mdDialog, queryFactory, spinFactory, language) {

  $scope.currentStep = $state;
  $scope.queryLen = 0;

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
