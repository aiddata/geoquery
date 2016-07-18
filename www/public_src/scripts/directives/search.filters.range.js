angular.module('aiddataDET')
.directive('searchFiltersRange', function($window) {
  return {
    restrict: "E",
    scope: {
      filterData: '=filterdata',
      filterOptions: '=filteroptions',
      activeFilters: '=activefilters'
    },
    link: function(scope, element, attrs) {},
    controller: "RangeCtrl",
    templateUrl: "views/components/search.filters.range.html"
  };
});
