angular.module('aiddataDET')
.controller('FiltersCtrl', function($scope, $rootScope, $stateParams, $q, filterFactory, $state) {
  $scope.filters = filterFactory.filters;
  $scope.searchData = filterFactory.filterOptions;

  $scope.filterInfo = {
    'ad_sector_names': { text: 'Sectors', type: 'options', searchFilter: '' },
    'donors': { text: 'Donors', type: 'options', searchFilter: '' },
    'years': { text: 'Years', type: 'range' }
  };

  $scope.updateFilters = function () {
    $rootScope.$broadcast('filters:update', $scope.filters);
    filterFactory.updateFilters()
      .then(function(filterOptions) {
        $rootScope.$broadcast('filters:updated', filterOptions);
      });
  };

  $scope.toggleFilter = function (filter, option) {
    $q.when(filterFactory.toggleFilter(filter, option))
      .then(function(filters) {
        console.log(filters);
        $scope.updateFilters();
      });
  };

  $scope.toggleAll = function (filter) {
    delete $scope.filters[filter];
    $scope.updateFilters();
  };

  $scope.allChecked = function(filter) {
    return !$scope.filters[filter];
  };

  $scope.isChecked = function(filter, option) {
    return $scope.filters[filter] &&
      $scope.filters[filter].indexOf(option) >= 0;
  };

  $rootScope.$on('dataset:selected', function(e, data) {
    filterFactory.setDataset(data.name);
    $scope.updateFilters();
  });


});
