angular.module('aiddataDET')
.controller('ListCtrl', function($scope, $rootScope, $log, queryFactory) {
  // $scope.filterData = {  };
  // $scope.filterOptions = [];
  // $scope.activeFilters = [];

  $scope.toggleFilter = function (filter, option) {
    var checked = $scope.activeFilters && $scope.activeFilters.indexOf(option) >= 0;
    return !checked ? queryFactory.toggleFilterOn(filter, option) :
      queryFactory.toggleFilterOff(filter, option);
  };

  $scope.toggleAll = function (filter) {
    queryFactory.resetFilter(filter);
  };

});
