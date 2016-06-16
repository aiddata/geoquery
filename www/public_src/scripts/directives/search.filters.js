angular.module('aiddataDET')
.directive('detFilters', function($window) {
  return {
    restrict: "E",
    controller: "FiltersCtrl",
    link: function(scope, element, attrs) {},
    templateUrl: "views/components/search.filters.html"
  };
});
