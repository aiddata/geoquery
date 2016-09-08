/**
  * This is the controller for instances of the process breadcrumbs directive
  */

angular.module('aiddataDET')
.controller('ProcessBreadcrumbsCtrl', function ($scope) {

  // sort order for step
  $scope.stepIndex = function(step) {
    return step.indexOf('submit') >= 0 ? 0 :
      step.indexOf('complete') >= 0 ? 2 : 1;
  };

  // display text for step
  $scope.stepText = function(step) {
    return step.indexOf('submit') >= 0 ? 'submitted' :
      step.indexOf('complete') >= 0 ? 'completed' : 'processed';
  };

  // current step sort order and display text
  $scope.currentStepIndex = $scope.stepIndex($scope.currentStep);
  $scope.currentStepName = $scope.stepText($scope.currentStep);

  // Default steps used if stepList is not defined
  $scope.defaultSteps = [
    { name: 'submit', time: true },
    { name: 'prep', time: true },
    { name: 'process', time: true },
    { name: 'complete', time: true }
  ];

});
