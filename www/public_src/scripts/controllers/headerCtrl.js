angular.module('aiddataDET')
.controller('HeaderCtrl', function($scope, $rootScope, $log, $stateParams, $state) {
  $scope.currentStep = $state;
  $scope.query = '{}';

  $rootScope.$on('query:updated', function(event, data) {
    $scope.query = JSON.stringify(data, null, 4);
  });

  $rootScope.$on('$stateChangeSuccess', function(event, toState, toParams, fromState, fromParams) {
    $scope.currentStep = toState;
  });

  $rootScope.$on('$stateChangeError', function(event, toState, toParams, fromState, fromParams, error){
    $log.error(event, toState, toParams, fromState, fromParams, error);
  });

});
