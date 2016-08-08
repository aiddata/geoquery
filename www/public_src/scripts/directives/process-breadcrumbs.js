angular.module('aiddataDET')
.directive('processBreadcrumbs', function($window) {
  return {
    restrict: 'E',
    scope: {
      currentStep: '=',
      stepList: '=',
      fullWidth: '='
    },
    controller: function ($scope) {
      $scope.defaultSteps = [
        { name: 'submit', time: true },
        { name: 'prep', time: true },
        { name: 'process', time: true },
        { name: 'complete', time: true }
      ];
    },
    templateUrl: "views/components/processBreadcrumbs.html"
  };
});
