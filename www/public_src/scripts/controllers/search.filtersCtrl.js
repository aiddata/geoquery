angular.module('aiddataDET')
.controller('FiltersCtrl', function($scope, $rootScope, $stateParams, $q, ajaxFactory, $state, $stateParams) {
  $scope.filters = { };
  $scope.searchData = { };

  $scope.filterInfo = {
    'ad_sector_names': { text: 'Sectors', type: 'options', searchFilter: '' },
    'donors': { text: 'Donors', type: 'options', searchFilter: '' },
    'years': { text: 'Years', type: 'range' }
  };

  $scope.updateFilters = function () {
    $rootScope.$broadcast('filters:update', $scope.filters);
    ajaxFactory.filters($scope.filters)
      .then(function(results) {
        $rootScope.$broadcast('filters:updated', results.data);
        $scope.searchData = results.data;
        $scope.searchData.filterTypes = _.keys($scope.searchData.distinct);

      }, function(err) {
        console.log(err);
      });
  };

  $scope.toggleFilter = function (filter, option) {
    var dir = !$scope.isChecked(filter, option);

    if (dir === true) {
      if (!$scope.filters[filter]) {
        $scope.filters[filter] = [];
      }
      $scope.filters[filter].push(option);
    } else {
      _.pull($scope.filters[filter], option);
      if (!$scope.filters[filter].length) {
        delete $scope.filters[filter];
      }
    }

    $scope.updateFilters();
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
    _.extend($scope.filters, { dataset : data.name });
    $scope.updateFilters();
  });


});
