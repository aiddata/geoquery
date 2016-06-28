angular.module('aiddataDET')
.controller('FiltersCtrl', function($scope, $rootScope, $stateParams, $q, $log, filterFactory, $state) {
  $scope.filterOptions = { };
  $scope.filters = filterFactory.filters;

  $scope.filterInfo = {
    'ad_sector_names': { text: 'Sectors', type: 'options', searchFilter: '' },
    'donors': { text: 'Donors', type: 'options', searchFilter: '' },
    'years': { text: 'Years', type: 'range' }
  };

  $scope.updateFilters = function () {
    $rootScope.$broadcast('filters:update', $scope.filters);
    filterFactory.updateFilters()
      .then(function(filterOptions) {
        $scope.filterOptions = filterOptions;
        $rootScope.$broadcast('filters:updated', filterOptions);
      });
  };

  $scope.toggleFilter = function (bool, filter, option) {
    return bool ? filterFactory.toggleFilterOn(filter, option) :
      filterFactory.toggleFilterOff(filter, option);
  };

  $scope.toggleAll = function (filter) {
    filterFactory.toggleAll(filter);
  };

  $rootScope.$on('dataset:selected', function(e, data) {
    filterFactory.setDataset(data.name);
  });

  $scope.$watch('filters', function(newValue, oldValue) {
    if (!_.isEqual(newValue, oldValue)) {
      $scope.updateFilters();
    }
  }, true);


});
