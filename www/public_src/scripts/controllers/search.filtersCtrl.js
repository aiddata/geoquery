angular.module('aiddataDET')
.controller('FiltersCtrl', function($scope, $rootScope, $log, queryFactory) {
  $scope.dataset = {};
  $scope.filterOptions = {};
  $scope.filters = queryFactory.filters;

  $scope.filterInfo = {
    'ad_sector_names': { text: 'Sectors', type: 'options', searchFilter: '' },
    'donors': { text: 'Donors', type: 'options', searchFilter: '' },
    'years': { text: 'Years', type: 'range' }
  };

  $scope.updateFilters = function () {
    $rootScope.$broadcast('filters:update', $scope.filters);
    queryFactory.updateFilters()
      .then(function(filterOptions) {
        $scope.filterOptions = filterOptions;
        $rootScope.$broadcast('filters:updated', filterOptions);
      });
  };

  $scope.toggleFilter = function (filter, option) {
    var checked = $scope.filters[filter] && $scope.filters[filter].indexOf(option) >= 0;
    return !checked ? queryFactory.toggleFilterOn(filter, option) :
      queryFactory.toggleFilterOff(filter, option);
  };

  $scope.toggleAll = function (filter) {
    queryFactory.toggleAll(filter);
  };

  $rootScope.$on('dataset:selected', function(e, data) {
    $scope.dataset = data;
    _.each($scope.filters, function(options, filter) {
      $scope.toggleAll(filter);
    });

    queryFactory.setDataset(data.name);
  });

  $scope.$watch('filters', function(newValue, oldValue) {
    if (!_.isEqual(newValue, oldValue)) {
      $scope.updateFilters();
    }
  }, true);

});
