angular.module('aiddataDET')
.controller('HeaderCtrl', function($scope, $rootScope, $log, $stateParams, $state, $timeout, queryFactory, spinFactory, info) {

  $scope.currentStep = $state;
  $scope.queryLen = 0;
  $scope.highlightRed = false;
  $scope.highlightGreen = false;

  $scope.activate = function (tab) {
    $scope.sidebarOpen = true;
    $rootScope.$broadcast('sidebar:open', tab);
  };

  $rootScope.$on('query:updated', function() {
    var oldSize = $scope.queryLen,
        newSize = queryFactory.querySize();
    $scope.queryLen = newSize;
    $scope.highlightRed = oldSize > newSize;
    $scope.highlightGreen = newSize > oldSize;

    $timeout(function() {
      $scope.highlightRed = false;
      $scope.highlightGreen = false;
    }, 2750);
  });

  $rootScope.$on('$viewContentLoaded', function() {
    $scope.currentStep = $state.current.name;
    $scope.showSteps = $scope.currentStep === 'map' ||
                       $scope.currentStep.indexOf('search') >= 0 ||
                       $scope.currentStep === 'checkout';
  });

});
