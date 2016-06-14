angular.module('aiddataDET')
.directive('geographySearch', function($window) {
  return {
    restrict: "E",
    controller: 'GeographySearchCtrl',
    scope: { },
    link:  { },
    templateUrl: "views/components/geographySearch.html"
  };
});
