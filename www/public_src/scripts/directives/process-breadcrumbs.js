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

      $scope.lastSteps = {
        submit: ['submit'],
        prep: ['prep', 'submit'],
        process: ['process', 'prep', 'submit'],
        complete: ['complete', 'process', 'prep', 'submit']
      };
    },
    templateUrl: "views/components/processBreadcrumbs.html"
  };
});
