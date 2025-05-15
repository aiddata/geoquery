angular.module('aiddataDET')
.directive('searchFiltersRange', function($window) {
  return {
    restrict: "E",
    scope: {
      filterData: '=filterData',
      filterOptions: '=filterOptions',
      activeFilters: '=activeFilters'
    },
    link: function(scope, element, attrs) {},
    controller: "RangeCtrl",
    templateUrl: "views/components/search.filters.range.html"
  };
});
