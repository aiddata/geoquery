angular.module('aiddataDET')
.directive('searchFiltersList', function($window) {
  return {
    restrict: "E",
    scope: {
      filterData: '=filterData',
      filterOptions: '=filterOptions',
      activeFilters: '=activeFilters'
    },
    link: function(scope, element, attrs) {},
    controller: "ListCtrl",
    templateUrl: "views/components/search.filters.list.html"
  };
});
