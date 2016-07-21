angular.module('aiddataDET')
.directive('detHeader', function($window) {
  return {
    restrict: "E",
    link: function(scope, element, attrs) {},
    templateUrl: "views/components/header.html",
    controller: function($scope, $rootScope, $log, $stateParams, $state) {
      $scope.currentStep = $state;
      console.log($scope.currentStep );
      $scope.query = '{}';

      $rootScope.$on('query:updated', function(event, data) {
        $scope.query = JSON.stringify(data, null, 4);
      });

      $rootScope.$on('$stateChangeSuccess', function(event, toState, toParams, fromState, fromParams) {
        $scope.currentStep = toState;
      });
    }
  };
});
