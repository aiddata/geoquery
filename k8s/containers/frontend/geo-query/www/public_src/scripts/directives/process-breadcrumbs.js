/**
  * This is the process breadcrumbs directive, which displays the various data
  * processing steps, highlighting the current one. It can appear on multiple
  * pages.
  */
angular.module('aiddataDET')
.directive('processBreadcrumbs', function($window) {
  return {
    restrict: 'E',
    scope: {
      currentStep: '=',
      stepList: '=',
      fullWidth: '=',
      stepHover: '='
    },
    controller: 'ProcessBreadcrumbsCtrl',
    templateUrl: "views/components/processBreadcrumbs.html"
  };
});
